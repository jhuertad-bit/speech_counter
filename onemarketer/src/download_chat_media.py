#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga medios de conversación OneMarketer enlazados a reporte_chats.

Flujo:
  1. getChats (reporteChats) ya cargó las líneas en reporte_chats.
  2. Se detectan líneas que son archivo (mime / sin texto).
  3. API descargachats aporta la URL en ``download`` por idcase+idmessage.
  4. Se descarga, sube a GCS y registra en reporte_whatsapp_documento_raw.
  5. Si es audio, convierte a MP3 (audio_to_mp3) y registra en reporte_whatsapp_mp3.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import sys
import tempfile
import time
from datetime import date, datetime
from typing import Any

import requests
from google.cloud import bigquery, storage

from bq_documentos import (
    delete_partition,
    ensure_table,
    insert_rows,
    load_media_keys_ok,
    load_mp3_keys_done,
    load_pending_mp3_audios,
    load_schema,
)
from extract_chats import load_config, parse_onemarketer_json_response
from gcp_runtime_log import get_runtime_service_account_email
from whatsapp_audio_mp3 import convert_whatsapp_audio_row

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


AUDIO_EXTENSIONS = {
    ".ogg", ".opus", ".wav", ".wave", ".flac", ".m4a", ".aac",
    ".wma", ".amr", ".3gp", ".mp4", ".webm", ".aiff", ".aif", ".caf", ".mp2", ".mp3",
}


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


def is_audio_for_mp3(
    mime: str | None,
    tipo: str | None = None,
    file_name: str | None = None,
    media_type: str | None = None,
    filter_cfg: dict[str, Any] | None = None,
) -> bool:
    """True si el archivo debe convertirse a MP3 (mime, extensión o media_type)."""
    if media_type == "audio" or resolve_media_type(mime, tipo) == "audio":
        return True
    if file_name:
        _, ext = os.path.splitext(file_name.lower())
        if ext in AUDIO_EXTENSIONS:
            return True
    if filter_cfg and _matches_patterns(mime, filter_cfg.get("mime_audio_patterns", [])):
        return True
    return False


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _convert_mp3_from_gcs_row(
    prior: dict[str, Any],
    *,
    gcp_config: dict[str, Any],
    mp3_cfg: dict[str, Any],
    fecha_evento: str,
    mime: str | None,
    now: str,
) -> dict[str, Any]:
    chat_line = {
        "idcase": prior.get("idcase"),
        "idmessage": prior.get("idmessage"),
        "waid": prior.get("waid"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        local_raw = os.path.join(tmp, prior["file_name"])
        _download_gcs_blob(gcp_config, prior["gcs_uri"], local_raw)
        return convert_whatsapp_audio_row(
            local_source_path=local_raw,
            storage_file_name=prior["file_name"],
            source_file_name=prior.get("source_file_name") or prior["file_name"],
            source_gcs_uri=prior["gcs_uri"],
            gcp_config=gcp_config,
            mp3_cfg=mp3_cfg,
            fecha_evento=fecha_evento,
            chat_line=chat_line,
            mime=mime or prior.get("mime"),
            now=now,
            tmp_dir=tmp,
        )


def _backfill_pending_mp3(
    *,
    fecha_evento: str,
    gcp_config: dict[str, Any],
    mp3_cfg: dict[str, Any],
    bq_cfg: dict[str, Any],
    mp3_bq_cfg: dict[str, Any],
    now: str,
    existing_mp3_keys: set[tuple[int, int]],
    mp3_rows: list[dict[str, Any]],
) -> tuple[int, int]:
    """Convierte audios ya en documento_raw que aún no tienen fila MP3."""
    project_id = gcp_config["project_id"]
    dataset_id = gcp_config["dataset_id"]
    doc_table = bq_cfg.get("table_id", "reporte_whatsapp_documento_raw")
    mp3_table = mp3_bq_cfg.get("table_id", "reporte_whatsapp_mp3")
    doc_ref = f"{project_id}.{dataset_id}.{doc_table}"
    mp3_ref = f"{project_id}.{dataset_id}.{mp3_table}"

    bq_client = bigquery.Client(project=project_id)
    pending = load_pending_mp3_audios(bq_client, doc_ref, mp3_ref, fecha_evento)
    if not pending:
        return 0, 0

    print(f"[mp3] Backfill: {len(pending)} audio(s) en documento_raw sin MP3")
    converted = 0
    failed = 0
    queued_keys = {
        (int(row["idcase"]), int(row["idmessage"]))
        for row in mp3_rows
        if row.get("idcase") is not None and row.get("idmessage") is not None
    }

    for row in pending:
        key = (int(row["idcase"]), int(row["idmessage"]))
        if key in existing_mp3_keys or key in queued_keys:
            continue
        print(
            f"  [mp3 backfill] idcase={row['idcase']} idmessage={row['idmessage']} "
            f"file={row.get('file_name')}"
        )
        try:
            mp3_row = _convert_mp3_from_gcs_row(
                row,
                gcp_config=gcp_config,
                mp3_cfg=mp3_cfg,
                fecha_evento=fecha_evento,
                mime=row.get("mime"),
                now=now,
            )
            mp3_rows.append(mp3_row)
            queued_keys.add(key)
            if mp3_row.get("conversion_status") == "OK":
                converted += 1
            elif mp3_row.get("conversion_status") == "FAILED":
                failed += 1
        except Exception as exc:
            failed += 1
            print(f"    [mp3 backfill] ✗ {exc}")

    return converted, failed


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


def _parse_gcs_uri(gcs_uri: str) -> tuple[str, str]:
    if not gcs_uri.startswith("gs://"):
        raise ValueError(f"URI GCS inválida: {gcs_uri}")
    rest = gcs_uri[5:]
    bucket, _, blob = rest.partition("/")
    return bucket, blob


def _download_gcs_blob(gcp_config: dict[str, Any], gcs_uri: str, dest_path: str) -> int:
    bucket_name, blob_name = _parse_gcs_uri(gcs_uri)
    client = storage.Client(project=gcp_config["project_id"])
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.download_to_filename(dest_path)
    return os.path.getsize(dest_path)


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
    force_reprocess: bool = False,
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
    mp3_cfg = media_cfg.get("audioToMp3", {})
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
    incremental = processing_cfg.get("incremental", True) and not force_reprocess
    now = datetime.now().isoformat()

    if force_reprocess:
        print("[onemarketer-media] Modo force_reprocess: reemplaza partición del día en BQ")
    elif incremental:
        print("[onemarketer-media] Modo incremental: solo archivos nuevos + MP3 pendientes")

    mp3_enabled = mp3_cfg.get("enabled", False) and upload_gcs
    mp3_bq_cfg = mp3_cfg.get("bigquery", {})
    if mp3_enabled:
        ffmpeg_ok = _ffmpeg_available()
        print(
            f"[mp3] enabled=True | tabla={mp3_bq_cfg.get('table_id', 'reporte_whatsapp_mp3')} | "
            f"gcs_path={mp3_cfg.get('gcs_path', '')} | ffmpeg={'OK' if ffmpeg_ok else 'NO ENCONTRADO'}"
        )
        if not ffmpeg_ok:
            print(
                "[mp3] ⚠️  Sin ffmpeg en runtime: la conversión fallará. "
                "Redespliega con imagen Docker (cloudbuild_deploy.sh)."
            )
        if mp3_bq_cfg.get("enabled", True) and gcp_config.get("project_id") and gcp_config.get("dataset_id"):
            mp3_table_id = mp3_bq_cfg.get("table_id", "reporte_whatsapp_mp3")
            mp3_partition_field = mp3_bq_cfg.get("partition_field", "fecha_evento")
            bq_boot = bigquery.Client(project=gcp_config["project_id"])
            mp3_schema = load_schema(mp3_table_id)
            ensure_table(
                bq_boot,
                gcp_config["project_id"],
                gcp_config["dataset_id"],
                mp3_table_id,
                mp3_schema,
                mp3_partition_field,
            )
            print(
                f"[mp3] Tabla BQ asegurada: "
                f"{gcp_config['project_id']}.{gcp_config['dataset_id']}.{mp3_table_id}"
            )
    else:
        print("[mp3] enabled=False (audioToMp3 deshabilitado o upload_gcs=false)")

    media_lines: dict[tuple[int | None, int | None], dict[str, Any]] = {}
    if chat_messages is not None:
        for msg in chat_messages:
            if is_media_chat_line(msg, filter_cfg):
                key = message_key(msg)
                if key[0] is not None and key[1] is not None:
                    media_lines[key] = msg
        print(f"Líneas de conversación tipo archivo en reporteChats: {len(media_lines)}")
        if match_chats_only and not media_lines:
            print("Sin líneas archivo nuevas; intentando solo backfill MP3 desde documento_raw.")
            mp3_rows: list[dict[str, Any]] = []
            mp3_converted = 0
            mp3_failed = 0
            if mp3_enabled and upload_gcs and not force_reprocess:
                mp3_converted, mp3_failed = _backfill_pending_mp3(
                    fecha_evento=fecha_evento,
                    gcp_config=gcp_config,
                    mp3_cfg=mp3_cfg,
                    bq_cfg=bq_cfg,
                    mp3_bq_cfg=mp3_bq_cfg,
                    now=now,
                    existing_mp3_keys=set(),
                    mp3_rows=mp3_rows,
                )
            if mp3_enabled and mp3_bq_cfg.get("enabled", True) and mp3_rows:
                project_id = gcp_config["project_id"]
                dataset_id = gcp_config["dataset_id"]
                mp3_table_id = mp3_bq_cfg.get("table_id", "reporte_whatsapp_mp3")
                bq_client = bigquery.Client(project=project_id)
                insert_rows(bq_client, dataset_id, mp3_table_id, mp3_rows)
                print(f"BigQuery MP3 (append): {len(mp3_rows)} filas en {project_id}.{dataset_id}.{mp3_table_id}")
            return {
                "fecha_evento": fecha_evento,
                "media_chat_lines": 0,
                "downloaded": 0,
                "skipped": True,
                "reason": "no_media_lines",
                "mp3_enabled": mp3_enabled,
                "mp3_rows": len(mp3_rows),
                "mp3_converted": mp3_converted,
                "mp3_failed": mp3_failed,
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
    mp3_rows: list[dict[str, Any]] = []
    downloaded = 0
    failed = 0
    mp3_converted = 0
    mp3_failed = 0
    skipped_no_match = 0
    skipped_existing = 0

    existing_media: dict[tuple[int, int], dict[str, Any]] = {}
    existing_mp3: set[tuple[int, int]] = set()
    if incremental and upload_gcs:
        project_id = gcp_config["project_id"]
        dataset_id = gcp_config["dataset_id"]
        doc_table = bq_cfg.get("table_id", "reporte_whatsapp_documento_raw")
        doc_ref = f"{project_id}.{dataset_id}.{doc_table}"
        bq_probe = bigquery.Client(project=project_id)
        existing_media = load_media_keys_ok(bq_probe, doc_ref, fecha_evento)
        if mp3_enabled:
            mp3_table = mp3_cfg.get("bigquery", {}).get("table_id", "reporte_whatsapp_mp3")
            mp3_ref = f"{project_id}.{dataset_id}.{mp3_table}"
            existing_mp3 = load_mp3_keys_done(bq_probe, mp3_ref, fecha_evento)
        print(
            f"[onemarketer-media] Ya en BQ fecha={fecha_evento}: "
            f"{len(existing_media)} docs OK, {len(existing_mp3)} mp3"
        )

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

        # Incremental: raw ya descargado → omitir HTTP; convertir MP3 si falta
        if incremental and key in existing_media:
            skipped_existing += 1
            prior = existing_media[key]
            print(f"    ⊘ ya descargado: {prior.get('gcs_uri')}")
            prior_audio = is_audio_for_mp3(
                mime or prior.get("mime"),
                tipo,
                prior.get("file_name"),
                prior.get("media_type") or media_type,
                filter_cfg,
            )
            if (
                mp3_enabled
                and prior_audio
                and key not in existing_mp3
                and prior.get("gcs_uri")
                and prior.get("file_name")
            ):
                try:
                    mp3_row = _convert_mp3_from_gcs_row(
                        prior,
                        gcp_config=gcp_config,
                        mp3_cfg=mp3_cfg,
                        fecha_evento=fecha_evento,
                        mime=mime or prior.get("mime"),
                        now=now,
                    )
                    mp3_rows.append(mp3_row)
                    if mp3_row.get("conversion_status") == "OK":
                        mp3_converted += 1
                    elif mp3_row.get("conversion_status") == "FAILED":
                        mp3_failed += 1
                except Exception as exc:
                    print(f"    [mp3] ✗ desde GCS existente: {exc}")
            elif mp3_enabled and prior_audio and key in existing_mp3:
                print("    [mp3] ya registrado en BQ")
            continue

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

                should_mp3 = is_audio_for_mp3(
                    mime, tipo, storage_file_name, media_type, filter_cfg
                )
                if mp3_enabled and should_mp3 and key not in existing_mp3:
                    mp3_row = convert_whatsapp_audio_row(
                        local_source_path=final_path,
                        storage_file_name=storage_file_name,
                        source_file_name=source_file_name,
                        source_gcs_uri=gcs_uri,
                        gcp_config=gcp_config,
                        mp3_cfg=mp3_cfg,
                        fecha_evento=fecha_evento,
                        chat_line=chat_line,
                        mime=mime,
                        now=now,
                        tmp_dir=tmp,
                    )
                    mp3_rows.append(mp3_row)
                    if mp3_row.get("conversion_status") == "OK":
                        mp3_converted += 1
                    elif mp3_row.get("conversion_status") == "FAILED":
                        mp3_failed += 1
        except requests.RequestException as exc:
            base_row["download_status"] = "FAILED"
            base_row["error_message"] = str(exc)[:500]
            failed += 1
            print(f"    ✗ {exc}")

        bq_rows.append(base_row)

    if mp3_enabled and upload_gcs and not force_reprocess:
        backfill_ok, backfill_fail = _backfill_pending_mp3(
            fecha_evento=fecha_evento,
            gcp_config=gcp_config,
            mp3_cfg=mp3_cfg,
            bq_cfg=bq_cfg,
            mp3_bq_cfg=mp3_bq_cfg,
            now=now,
            existing_mp3_keys=existing_mp3,
            mp3_rows=mp3_rows,
        )
        mp3_converted += backfill_ok
        mp3_failed += backfill_fail

    if bq_cfg.get("enabled", True) and bq_rows and upload_gcs:
        project_id = gcp_config["project_id"]
        dataset_id = gcp_config["dataset_id"]
        table_id = bq_cfg.get("table_id", "reporte_whatsapp_documento_raw")
        partition_field = bq_cfg.get("partition_field", "fecha_evento")

        bq_client = bigquery.Client(project=project_id)
        schema = load_schema(table_id)
        table_ref = ensure_table(bq_client, project_id, dataset_id, table_id, schema, partition_field)
        if force_reprocess:
            delete_partition(bq_client, table_ref, fecha_evento, partition_field)
        insert_rows(bq_client, dataset_id, table_id, bq_rows)
        mode = "reemplazo" if force_reprocess else "append"
        print(f"BigQuery ({mode}): {len(bq_rows)} filas nuevas en {table_ref}")

    if mp3_enabled and mp3_bq_cfg.get("enabled", True) and mp3_rows:
        project_id = gcp_config["project_id"]
        dataset_id = gcp_config["dataset_id"]
        mp3_table_id = mp3_bq_cfg.get("table_id", "reporte_whatsapp_mp3")
        mp3_partition_field = mp3_bq_cfg.get("partition_field", "fecha_evento")

        bq_client = bigquery.Client(project=project_id)
        mp3_schema = load_schema(mp3_table_id)
        mp3_table_ref = ensure_table(
            bq_client, project_id, dataset_id, mp3_table_id, mp3_schema, mp3_partition_field
        )
        if force_reprocess:
            delete_partition(bq_client, mp3_table_ref, fecha_evento, mp3_partition_field)
        insert_rows(bq_client, dataset_id, mp3_table_id, mp3_rows)
        mode = "reemplazo" if force_reprocess else "append"
        print(f"BigQuery MP3 ({mode}): {len(mp3_rows)} filas nuevas en {mp3_table_ref}")

    summary = {
        "fecha_evento": fecha_evento,
        "media_chat_lines": len(media_lines),
        "download_api_urls": len(download_index),
        "matched_and_processed": len(keys_to_process),
        "downloaded": downloaded,
        "skipped_existing": skipped_existing,
        "failed": failed,
        "incremental": incremental,
        "force_reprocess": force_reprocess,
        "mp3_enabled": mp3_enabled,
        "mp3_rows": len(mp3_rows),
        "mp3_converted": mp3_converted,
        "mp3_failed": mp3_failed,
        "ffmpeg_available": _ffmpeg_available() if mp3_enabled else None,
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
    parser.add_argument(
        "--force-reprocess",
        action="store_true",
        help="Borra partición BQ del día y redescarga todo (desactiva incremental)",
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

    result = process_media_for_date(
        args.fecha,
        config,
        chat_messages=chat_messages,
        force_reprocess=args.force_reprocess,
    )
    if result.get("failed", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main_cli()
