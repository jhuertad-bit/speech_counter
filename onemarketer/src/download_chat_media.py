#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga medios de conversación OneMarketer enlazados a reporte_chats.

Flujo:
  1. getChats (reporteChats) ya cargó las líneas en reporte_chats.
  2. Se detectan líneas que son archivo (mime / sin texto).
  3. API descargachats aporta la URL en ``download`` por idcase+idmessage.
  4. Se descarga, sube a GCS (whatsapp_documentos_raw) y registra en
     reporte_whatsapp_documento_raw.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import tempfile
import time
from datetime import date, datetime
from typing import Any

import requests
from google.cloud import bigquery, storage

from bq_documentos import delete_partition, ensure_table, insert_rows, load_schema
from extract_chats import load_config, parse_onemarketer_json_response
from gcp_runtime_log import get_runtime_service_account_email

CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "video/mp4": ".mp4",
}


def _matches_patterns(value: str | None, patterns: list[str]) -> bool:
    if not value or not patterns:
        return False
    lower = value.lower()
    return any(p.lower() in lower for p in patterns)


def message_key(record: dict[str, Any]) -> tuple[int | None, int | None]:
    idcase = record.get("idcase")
    idmessage = record.get("idmessage")
    try:
        return (int(idcase) if idcase is not None else None, int(idmessage) if idmessage is not None else None)
    except (TypeError, ValueError):
        return (None, None)


def is_media_chat_line(message: dict[str, Any], filter_cfg: dict[str, Any]) -> bool:
    """True si la línea de reporteChats representa un adjunto (no texto plano)."""
    mime = (message.get("mime") or "").strip().lower()
    text = (message.get("text") or "").strip()

    skip_patterns = filter_cfg.get("mime_skip_patterns", ["text/plain", "text/html"])
    if mime and any(s in mime for s in skip_patterns):
        return False

    audio_patterns = filter_cfg.get(
        "mime_audio_patterns",
        ["audio", "ogg", "opus", "mpeg", "ptt", "voice", "amr"],
    )
    media_patterns = filter_cfg.get(
        "mime_media_patterns",
        ["image", "video", "document", "pdf", "application/"],
    )

    if _matches_patterns(mime, audio_patterns) or _matches_patterns(mime, media_patterns):
        return True

    if not text and mime and "text" not in mime:
        return True

    return False


def resolve_media_type(mime: str | None, tipo_objeto: str | None = None) -> str:
    combined = f"{mime or ''} {tipo_objeto or ''}".lower()
    if any(p in combined for p in ("audio", "ogg", "opus", "ptt", "voice", "mpeg", "amr")):
        return "audio"
    if "image" in combined:
        return "image"
    if "video" in combined:
        return "video"
    if any(p in combined for p in ("pdf", "document", "application")):
        return "document"
    return "unknown"


def get_download_api(api_cfg: dict[str, Any], fechaini: str) -> dict[str, Any]:
    base_url = api_cfg["base_url"]
    context = api_cfg.get("context", 1)
    key = api_cfg["key"]
    timeout = api_cfg.get("timeout", 300)
    max_retries = api_cfg.get("max_retries", 3)
    retry_delay = api_cfg.get("retry_delay", 5)
    auth_mode = api_cfg.get("auth_mode", "header")

    params = {"context": context, "fechaini": fechaini}
    headers = {"Content-Type": "application/json"}
    if auth_mode == "header":
        headers["key"] = key
    elif auth_mode == "query":
        params["key"] = key
    else:
        raise ValueError(f"auth_mode inválido: {auth_mode}")

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            if attempt > 0:
                print(f"Reintento descargachats {attempt + 1}/{max_retries}...")
                time.sleep(retry_delay)
            print(f"API descargachats: context={context}, fechaini={fechaini}")
            response = requests.get(base_url, headers=headers, params=params, timeout=timeout)
            response.raise_for_status()
            response.encoding = "utf-8"
            data = parse_onemarketer_json_response(response.text)
            print(f"descargachats status: {data.get('status')}")
            return data
        except requests.RequestException as exc:
            last_error = exc
            print(f"Error descargachats intento {attempt + 1}: {exc}")

    raise RuntimeError(f"descargachats falló tras {max_retries} intentos: {last_error}") from last_error


def _filename_from_response(response: requests.Response, default_stem: str) -> str:
    content_disp = response.headers.get("Content-Disposition", "")
    if "filename=" in content_disp:
        name = content_disp.split("filename=")[-1].strip().strip('"').strip("'")
        if name:
            return name
    mime = response.headers.get("Content-Type", "").split(";")[0].strip()
    ext = CONTENT_TYPE_EXT.get(mime) or mimetypes.guess_extension(mime) or ""
    return f"{default_stem}{ext}" if ext else default_stem


def download_to_path(url: str, dest_path: str, timeout: int) -> tuple[str, int]:
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        filename = _filename_from_response(response, os.path.basename(dest_path))
        if not os.path.splitext(dest_path)[1] and os.path.splitext(filename)[1]:
            dest_path = os.path.join(os.path.dirname(dest_path), filename)
        size = 0
        with open(dest_path, "wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
                    size += len(chunk)
    return dest_path, size


def _object_name(template: str, chat_line: dict[str, Any], media_type: str, extension: str) -> str:
    idcase = str(chat_line.get("idcase", "unknown"))
    idmessage = str(chat_line.get("idmessage", "unknown"))
    base = template.format(idcase=idcase, idmessage=idmessage, media_type=media_type)
    if extension and not extension.startswith("."):
        extension = f".{extension}"
    if extension and not base.lower().endswith(extension.lower()):
        return f"{base}{extension}"
    return base


def _upload_blob(
    local_path: str,
    gcp_config: dict[str, Any],
    gcs_prefix: str,
    fecha_evento: str,
    object_name: str,
) -> str:
    project_id = gcp_config["project_id"]
    bucket_name = gcp_config["bucket_name"]
    # gs://{bucket}/{gcs_path}/{fecha}/media/{archivo}
    blob_name = f"{gcs_prefix.rstrip('/')}/{fecha_evento}/media/{object_name}"

    client = storage.Client(project=project_id)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_path)
    return f"gs://{bucket_name}/{blob_name}"


def _index_download_records(records: list[dict[str, Any]]) -> dict[tuple[int | None, int | None], dict[str, Any]]:
    index: dict[tuple[int | None, int | None], dict[str, Any]] = {}
    for record in records:
        url = (record.get("download") or "").strip()
        if not url:
            continue
        key = message_key(record)
        if key[0] is None or key[1] is None:
            continue
        index[key] = record
    return index


def process_media_for_date(
    fecha_evento: str,
    config: dict[str, Any] | None = None,
    chat_messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cfg = config or load_config("config/config.json")
    gcp_config = cfg.get("gcp", {})
    print(
        f"[onemarketer-media] Inicio fecha={fecha_evento} | "
        f"SA runtime={get_runtime_service_account_email()} | "
        f"bucket={gcp_config.get('bucket_name', '')} | "
        f"dataset={gcp_config.get('dataset_id', '')}"
    )
    media_cfg = cfg.get("descargaChatsMedia", {})
    if not media_cfg.get("enabled", False):
        print("descargaChatsMedia deshabilitado.")
        return {"skipped": True, "reason": "disabled"}

    api_cfg = media_cfg.get("api", {})
    filter_cfg = media_cfg.get("filter", {})
    storage_cfg = media_cfg.get("storage", {})
    processing_cfg = media_cfg.get("processing", {})
    bq_cfg = media_cfg.get("bigquery", {})
    gcp_config = cfg.get("gcp", {})

    fechaini = api_cfg.get("fechaini") or fecha_evento
    timeout = int(processing_cfg.get("download_timeout_seconds", 120))
    max_files = int(processing_cfg.get("max_files_per_run", 500))
    upload_gcs = storage_cfg.get("upload_gcs", True)
    gcs_path = storage_cfg.get("gcs_path", "utp_pregrado/whatsapp_documentos_raw")
    name_template = processing_cfg.get(
        "filename_template",
        "{idcase}_{idmessage}_{media_type}",
    )
    match_chats_only = filter_cfg.get("match_reporte_chats_only", True)
    now = datetime.now().isoformat()

    media_lines: dict[tuple[int | None, int | None], dict[str, Any]] = {}
    if chat_messages is not None:
        for msg in chat_messages:
            if is_media_chat_line(msg, filter_cfg):
                key = message_key(msg)
                if key[0] is not None and key[1] is not None:
                    media_lines[key] = msg
        print(f"Líneas de conversación tipo archivo en reporteChats: {len(media_lines)}")
        if match_chats_only and not media_lines:
            print("Sin líneas archivo; no se llama a descargachats.")
            return {
                "fecha_evento": fecha_evento,
                "media_chat_lines": 0,
                "downloaded": 0,
                "skipped": True,
                "reason": "no_media_lines",
            }
    elif match_chats_only:
        print("match_reporte_chats_only=true pero no hay mensajes de reporteChats.")
        return {"skipped": True, "reason": "missing_chat_messages"}

    download_data = get_download_api(api_cfg, fechaini)
    download_records = download_data.get("data", [])
    download_index = _index_download_records(download_records)
    print(f"Registros descargachats con URL download: {len(download_index)}")

    if match_chats_only and media_lines:
        keys_to_process = [k for k in media_lines if k in download_index]
        unmatched_chat = [k for k in media_lines if k not in download_index]
        if unmatched_chat:
            print(f"⚠️  {len(unmatched_chat)} líneas archivo sin URL en descargachats (primeras 5): {unmatched_chat[:5]}")
    else:
        keys_to_process = list(download_index.keys())

    bq_rows: list[dict[str, Any]] = []
    downloaded = 0
    failed = 0
    skipped_no_match = 0

    for key in keys_to_process:
        if downloaded >= max_files:
            print(f"Límite max_files_per_run={max_files} alcanzado.")
            break

        dl_record = download_index[key]
        chat_line = media_lines.get(key, dl_record)
        download_url = (dl_record.get("download") or "").strip()
        if not download_url:
            skipped_no_match += 1
            continue

        mime = chat_line.get("mime") or dl_record.get("mime")
        tipo = dl_record.get("tipo_objeto") or dl_record.get("tipo")
        media_type = resolve_media_type(mime, tipo)
        idmessage = chat_line.get("idmessage")

        base_row: dict[str, Any] = {
            "fecha_evento": fecha_evento,
            "fecha_procesamiento": now,
            "idcase": chat_line.get("idcase"),
            "idmessage": idmessage,
            "waid": chat_line.get("waid"),
            "mime": mime,
            "media_type": media_type,
            "content_source": "download_api",
            "source_url": download_url,
            "source_file_name": None,
            "gcs_uri": None,
            "file_name": None,
            "file_size_bytes": None,
            "download_status": None,
            "error_message": None,
        }

        print(f"  [{media_type}] idcase={chat_line.get('idcase')} idmessage={idmessage}")

        try:
            with tempfile.TemporaryDirectory() as tmp:
                temp_path = os.path.join(tmp, str(idmessage))
                final_path, file_size = download_to_path(download_url, temp_path, timeout)
                _, ext = os.path.splitext(final_path)
                object_name = _object_name(name_template, chat_line, media_type, ext)
                # Nombre que devolvió el servidor HTTP (Content-Disposition / MIME)
                source_file_name = os.path.basename(final_path)
                # file_name = nombre en GCS (debe calzar con el final de gcs_uri)
                storage_file_name = object_name

                gcs_uri = None
                if upload_gcs:
                    gcs_uri = _upload_blob(
                        final_path, gcp_config, gcs_path, fecha_evento, object_name
                    )
                    print(f"    → {gcs_uri}")
                elif storage_cfg.get("save_local_files", True):
                    local_dir = storage_cfg.get("local_dir", "descarga")
                    folder = os.path.join(local_dir, str(idmessage))
                    os.makedirs(folder, exist_ok=True)
                    dest = os.path.join(folder, storage_file_name)
                    with open(final_path, "rb") as src, open(dest, "wb") as dst:
                        dst.write(src.read())
                    print(f"    → local {dest}")

                base_row["source_file_name"] = source_file_name
                base_row["gcs_uri"] = gcs_uri
                base_row["file_name"] = storage_file_name
                base_row["file_size_bytes"] = file_size
                base_row["download_status"] = "OK"
                downloaded += 1
        except requests.RequestException as exc:
            base_row["download_status"] = "FAILED"
            base_row["error_message"] = str(exc)[:500]
            failed += 1
            print(f"    ✗ {exc}")

        bq_rows.append(base_row)

    if bq_cfg.get("enabled", True) and bq_rows and upload_gcs:
        project_id = gcp_config["project_id"]
        dataset_id = gcp_config["dataset_id"]
        table_id = bq_cfg.get("table_id", "reporte_whatsapp_documento_raw")
        partition_field = bq_cfg.get("partition_field", "fecha_evento")

        bq_client = bigquery.Client(project=project_id)
        schema = load_schema(table_id)
        table_ref = ensure_table(bq_client, project_id, dataset_id, table_id, schema, partition_field)
        delete_partition(bq_client, table_ref, fecha_evento, partition_field)
        insert_rows(bq_client, dataset_id, table_id, bq_rows)
        print(f"BigQuery: {len(bq_rows)} filas en {table_ref}")

    summary = {
        "fecha_evento": fecha_evento,
        "media_chat_lines": len(media_lines),
        "download_api_urls": len(download_index),
        "matched_and_processed": len(keys_to_process),
        "downloaded": downloaded,
        "failed": failed,
        "bq_rows": len(bq_rows),
    }
    print(f"\nResumen medios: {summary}")
    return summary


def main_cli() -> None:
    parser = argparse.ArgumentParser(
        description="Descarga medios enlazados a líneas archivo de reporteChats."
    )
    parser.add_argument("--fecha", type=str, default=date.today().isoformat())
    parser.add_argument("--context", type=int)
    parser.add_argument(
        "--config",
        default=os.path.join(os.path.dirname(__file__), "config", "config.json"),
    )
    parser.add_argument("--local-only", action="store_true")
    parser.add_argument(
        "--from-jsonl",
        help="JSONL de reporteChats para emparejar sin volver a extraer",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    media_cfg = config.setdefault("descargaChatsMedia", {})
    media_cfg.setdefault("enabled", True)
    media_cfg.setdefault("api", {})["fechaini"] = args.fecha
    if args.context is not None:
        media_cfg["api"]["context"] = args.context
    if args.local_only:
        media_cfg.setdefault("storage", {})["upload_gcs"] = False
        media_cfg["storage"]["save_local_files"] = True
        media_cfg.setdefault("bigquery", {})["enabled"] = False

    chat_messages = None
    if args.from_jsonl:
        chat_messages = []
        with open(args.from_jsonl, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    chat_messages.append(json.loads(line))

    result = process_media_for_date(args.fecha, config, chat_messages=chat_messages)
    if result.get("failed", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main_cli()
