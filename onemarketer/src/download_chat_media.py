#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Descarga medios de conversación OneMarketer enlazados a reporte_chats.

Flujo:
  1. getChats (reporteChats) ya cargó las líneas en reporte_chats.
  2. Se detectan líneas que son archivo (mime / sin texto).
  3. API descargachats aporta la URL en ``download`` por idcase+idmessage.
  4. Se descarga, sube a GCS y registra en reporte_whatsapp_documento_raw.
  5. Si es audio, convierte a MP3 y registra en reporte_whatsapp_mp3.
  6. Si es imagen, optimiza a WebP/AVIF en newimages y actualiza documento_raw.gcs_uri.
  7. Si es imagen o PDF, extrae texto (OCR) en reporte_whatsapp_ocr.
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
    load_documento_optimized_image_keys,
    load_mp3_keys_done,
    load_ocr_keys_done,
    load_pending_mp3_audios,
    load_pending_ocr_documents,
    load_pending_optimized_images,
    load_schema,
    update_documento_raw_storage,
)
from extract_chats import load_config, parse_onemarketer_json_response
from gcp_runtime_log import get_runtime_service_account_email
from converter import VIDEO_AUDIO_EXTENSIONS, is_video_audio_container
from image_converter import is_image_for_optimize
from ocr_engine import is_ocr_candidate, is_pdf
from whatsapp_audio_mp3 import convert_whatsapp_audio_row
from whatsapp_image_optim import convert_whatsapp_image_row
from whatsapp_ocr import convert_whatsapp_ocr_row

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
    "video/mpeg": ".mpeg",
    "video/mpg": ".mpg",
    "video/x-mpeg": ".mpeg",
    "video/quicktime": ".mov",
    "video/x-msvideo": ".avi",
    "video/x-matroska": ".mkv",
    "video/webm": ".webm",
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
} | VIDEO_AUDIO_EXTENSIONS


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
    if filter_cfg and _matches_patterns(
        mime, filter_cfg.get("mime_video_audio_patterns", [])
    ):
        return True
    if mime:
        ml = mime.lower()
        if any(
            p in ml
            for p in ("video/mpeg", "video/mpg", "video/x-mpeg", "video/quicktime")
        ):
            return True
    if file_name and is_video_audio_container(file_name):
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
    storage_gcs_path: str,
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
            storage_gcs_path=storage_gcs_path,
        )


def _backfill_pending_mp3(
    *,
    fecha_evento: str,
    gcp_config: dict[str, Any],
    mp3_cfg: dict[str, Any],
    storage_gcs_path: str,
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
                storage_gcs_path=storage_gcs_path,
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


def _pillow_available() -> bool:
    try:
        import PIL  # noqa: F401

        return True
    except ImportError:
        return False


def _convert_image_from_gcs_row(
    prior: dict[str, Any],
    *,
    gcp_config: dict[str, Any],
    img_cfg: dict[str, Any],
    fecha_evento: str,
    storage_gcs_path: str,
    mime: str | None,
    media_type: str | None,
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
        return convert_whatsapp_image_row(
            local_source_path=local_raw,
            storage_file_name=prior["file_name"],
            source_file_name=prior.get("source_file_name") or prior["file_name"],
            source_gcs_uri=prior["gcs_uri"],
            gcp_config=gcp_config,
            img_cfg=img_cfg,
            fecha_evento=fecha_evento,
            chat_line=chat_line,
            mime=mime or prior.get("mime"),
            media_type=media_type or prior.get("media_type"),
            now=now,
            tmp_dir=tmp,
            storage_gcs_path=storage_gcs_path,
        )


def _backfill_pending_images(
    *,
    fecha_evento: str,
    gcp_config: dict[str, Any],
    img_cfg: dict[str, Any],
    storage_gcs_path: str,
    bq_cfg: dict[str, Any],
    now: str,
    existing_image_keys: set[tuple[int, int]],
    processed_keys: set[tuple[int, int]],
) -> tuple[int, int]:
    project_id = gcp_config["project_id"]
    dataset_id = gcp_config["dataset_id"]
    doc_table = bq_cfg.get("table_id", "reporte_whatsapp_documento_raw")
    doc_ref = f"{project_id}.{dataset_id}.{doc_table}"
    subfolder = img_cfg.get("gcs_subfolder", "newimages")

    bq_client = bigquery.Client(project=project_id)
    pending = load_pending_optimized_images(
        bq_client, doc_ref, fecha_evento, optimized_subfolder=subfolder
    )
    if not pending:
        return 0, 0

    print(f"[img] Backfill: {len(pending)} imagen(es) en documento_raw sin optimizar")
    converted = 0
    failed = 0

    for row in pending:
        key = (int(row["idcase"]), int(row["idmessage"]))
        if key in existing_image_keys or key in processed_keys:
            continue
        print(
            f"  [img backfill] idcase={row['idcase']} idmessage={row['idmessage']} "
            f"file={row.get('file_name')}"
        )
        try:
            img_row = _convert_image_from_gcs_row(
                row,
                gcp_config=gcp_config,
                img_cfg=img_cfg,
                fecha_evento=fecha_evento,
                storage_gcs_path=storage_gcs_path,
                mime=row.get("mime"),
                media_type=row.get("media_type"),
                now=now,
            )
            processed_keys.add(key)
            if img_row.get("conversion_status") == "OK":
                converted += 1
            elif img_row.get("conversion_status") == "FAILED":
                failed += 1
            _finalize_image_only_storage(
                gcp_config=gcp_config,
                img_cfg=img_cfg,
                bq_cfg=bq_cfg,
                fecha_evento=fecha_evento,
                idcase=row.get("idcase"),
                idmessage=row.get("idmessage"),
                original_gcs_uri=row.get("gcs_uri"),
                img_row=img_row,
            )
        except Exception as exc:
            failed += 1
            print(f"    [img backfill] ✗ {exc}")

    return converted, failed


def _vision_available() -> bool:
    try:
        from google.cloud import vision  # noqa: F401

        return True
    except ImportError:
        return False


def _convert_ocr_from_gcs_row(
    prior: dict[str, Any],
    *,
    gcp_config: dict[str, Any],
    ocr_cfg: dict[str, Any],
    fecha_evento: str,
    mime: str | None,
    media_type: str | None,
    now: str,
) -> dict[str, Any]:
    chat_line = {
        "idcase": prior.get("idcase"),
        "idmessage": prior.get("idmessage"),
        "waid": prior.get("waid"),
    }
    file_name = prior["file_name"]
    needs_local = is_pdf(file_name, mime or prior.get("mime"))

    with tempfile.TemporaryDirectory() as tmp:
        local_path = None
        if needs_local:
            local_path = os.path.join(tmp, os.path.basename(file_name))
            _download_gcs_blob(gcp_config, prior["gcs_uri"], local_path)
        return convert_whatsapp_ocr_row(
            local_source_path=local_path,
            storage_file_name=file_name,
            source_file_name=prior.get("source_file_name") or file_name,
            source_gcs_uri=prior["gcs_uri"],
            optimized_gcs_uri=prior.get("optimized_gcs_uri"),
            gcp_config=gcp_config,
            ocr_cfg=ocr_cfg,
            fecha_evento=fecha_evento,
            chat_line=chat_line,
            mime=mime or prior.get("mime"),
            media_type=media_type or prior.get("media_type"),
            now=now,
        )


def _backfill_pending_ocr(
    *,
    fecha_evento: str,
    gcp_config: dict[str, Any],
    ocr_cfg: dict[str, Any],
    bq_cfg: dict[str, Any],
    ocr_bq_cfg: dict[str, Any],
    now: str,
    existing_ocr_keys: set[tuple[int, int]],
    ocr_rows: list[dict[str, Any]],
) -> tuple[int, int]:
    project_id = gcp_config["project_id"]
    dataset_id = gcp_config["dataset_id"]
    doc_table = bq_cfg.get("table_id", "reporte_whatsapp_documento_raw")
    ocr_table = ocr_bq_cfg.get("table_id", "reporte_whatsapp_ocr")
    doc_ref = f"{project_id}.{dataset_id}.{doc_table}"
    ocr_ref = f"{project_id}.{dataset_id}.{ocr_table}"

    bq_client = bigquery.Client(project=project_id)
    pending = load_pending_ocr_documents(bq_client, doc_ref, ocr_ref, fecha_evento)
    if not pending:
        return 0, 0

    print(f"[ocr] Backfill: {len(pending)} documento(s) sin OCR")
    converted = 0
    failed = 0
    queued_keys = {
        (int(row["idcase"]), int(row["idmessage"]))
        for row in ocr_rows
        if row.get("idcase") is not None and row.get("idmessage") is not None
    }

    for row in pending:
        key = (int(row["idcase"]), int(row["idmessage"]))
        if key in existing_ocr_keys or key in queued_keys:
            continue
        print(
            f"  [ocr backfill] idcase={row['idcase']} idmessage={row['idmessage']} "
            f"file={row.get('file_name')}"
        )
        try:
            ocr_row = _convert_ocr_from_gcs_row(
                row,
                gcp_config=gcp_config,
                ocr_cfg=ocr_cfg,
                fecha_evento=fecha_evento,
                mime=row.get("mime"),
                media_type=row.get("media_type"),
                now=now,
            )
            ocr_rows.append(ocr_row)
            queued_keys.add(key)
            if ocr_row.get("ocr_status") == "OK":
                converted += 1
            elif ocr_row.get("ocr_status") == "FAILED":
                failed += 1
        except Exception as exc:
            failed += 1
            print(f"    [ocr backfill] ✗ {exc}")

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


_IMAGE_OPT_OK = frozenset({"OK", "SKIPPED_EXISTS", "SKIPPED_ALREADY_OPTIMIZED"})


def _image_store_original(img_cfg: dict[str, Any]) -> bool:
    return bool(img_cfg.get("image", {}).get("store_original", False))


def _image_opt_success(img_row: dict[str, Any] | None) -> bool:
    return img_row is not None and img_row.get("conversion_status") in _IMAGE_OPT_OK


def _optimized_mime(img_cfg: dict[str, Any]) -> str:
    fmt = (img_cfg.get("image", {}).get("output_format") or "webp").lower()
    return "image/avif" if fmt == "avif" else "image/webp"


def _is_under_gcs_subfolder(gcs_uri: str | None, subfolder: str) -> bool:
    return f"/{subfolder.strip('/')}/" in (gcs_uri or "")


def _delete_gcs_blob(gcp_config: dict[str, Any], gcs_uri: str) -> bool:
    if not gcs_uri or not gcs_uri.startswith("gs://"):
        return False
    bucket_name, blob_name = _parse_gcs_uri(gcs_uri)
    client = storage.Client(project=gcp_config["project_id"])
    blob = client.bucket(bucket_name).blob(blob_name)
    if blob.exists():
        blob.delete()
        return True
    return False


def _apply_img_row_to_documento(
    base_row: dict[str, Any],
    img_row: dict[str, Any],
    img_cfg: dict[str, Any],
) -> None:
    base_row["gcs_uri"] = img_row["gcs_uri"]
    base_row["file_name"] = img_row["file_name"]
    if img_row.get("file_size_bytes") is not None:
        base_row["file_size_bytes"] = img_row["file_size_bytes"]
    base_row["mime"] = _optimized_mime(img_cfg)


def _finalize_image_only_storage(
    *,
    gcp_config: dict[str, Any],
    img_cfg: dict[str, Any],
    bq_cfg: dict[str, Any],
    fecha_evento: str,
    idcase: int | None,
    idmessage: int | None,
    original_gcs_uri: str | None,
    img_row: dict[str, Any],
) -> None:
    """Elimina original en media/ y actualiza documento_raw cuando solo se guarda optimizado."""
    if _image_store_original(img_cfg) or not _image_opt_success(img_row):
        return

    optimized_uri = img_row.get("gcs_uri")
    subfolder = img_cfg.get("gcs_subfolder", "newimages")
    if (
        original_gcs_uri
        and original_gcs_uri != optimized_uri
        and not _is_under_gcs_subfolder(original_gcs_uri, subfolder)
    ):
        if _delete_gcs_blob(gcp_config, original_gcs_uri):
            print(f"    [img] original eliminado: {original_gcs_uri}")

    if original_gcs_uri and _is_under_gcs_subfolder(original_gcs_uri, subfolder):
        return
    if not bq_cfg.get("enabled", True) or idcase is None or idmessage is None:
        return

    project_id = gcp_config.get("project_id")
    dataset_id = gcp_config.get("dataset_id")
    if not project_id or not dataset_id or not optimized_uri:
        return

    table_id = bq_cfg.get("table_id", "reporte_whatsapp_documento_raw")
    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    client = bigquery.Client(project=project_id)
    update_documento_raw_storage(
        client,
        table_ref,
        fecha_evento,
        int(idcase),
        int(idmessage),
        optimized_uri,
        img_row["file_name"],
        img_row.get("file_size_bytes"),
        _optimized_mime(img_cfg),
    )
    print(f"    [img] documento_raw actualizado → {optimized_uri}")


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
    img_cfg = media_cfg.get("imagesOptimize", {})
    ocr_cfg = media_cfg.get("textExtraction", {})
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
            f"gcs={gcs_path}/{{fecha}}/{mp3_cfg.get('gcs_subfolder', 'mp3')} | "
            f"ffmpeg={'OK' if ffmpeg_ok else 'NO ENCONTRADO'}"
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

    img_enabled = img_cfg.get("enabled", False) and upload_gcs
    if img_enabled:
        output_fmt = img_cfg.get("image", {}).get("output_format", "webp")
        store_orig = _image_store_original(img_cfg)
        print(
            f"[img] enabled=True | formato={output_fmt} | "
            f"store_original={store_orig} | "
            f"destino=documento_raw.gcs_uri → {gcs_path}/{{fecha}}/{img_cfg.get('gcs_subfolder', 'newimages')} | "
            f"pillow={'OK' if _pillow_available() else 'NO INSTALADO'}"
        )
        if not _pillow_available():
            print("[img] ⚠️  Instala Pillow (requirements.txt) para optimizar imágenes.")
    else:
        print("[img] enabled=False (imagesOptimize deshabilitado o upload_gcs=false)")

    ocr_enabled = ocr_cfg.get("enabled", False) and upload_gcs
    ocr_bq_cfg = ocr_cfg.get("bigquery", {})
    if ocr_enabled:
        print(
            f"[ocr] enabled=True | engine={ocr_cfg.get('engine', 'vision_api')} | "
            f"tabla={ocr_bq_cfg.get('table_id', 'reporte_whatsapp_ocr')} | "
            f"vision={'OK' if _vision_available() else 'NO INSTALADO'}"
        )
        if not _vision_available():
            print("[ocr] ⚠️  Instala google-cloud-vision (requirements.txt).")
        if ocr_bq_cfg.get("enabled", True) and gcp_config.get("project_id") and gcp_config.get("dataset_id"):
            ocr_table_id = ocr_bq_cfg.get("table_id", "reporte_whatsapp_ocr")
            ocr_partition_field = ocr_bq_cfg.get("partition_field", "fecha_evento")
            bq_boot = bigquery.Client(project=gcp_config["project_id"])
            ocr_schema = load_schema(ocr_table_id)
            ensure_table(
                bq_boot,
                gcp_config["project_id"],
                gcp_config["dataset_id"],
                ocr_table_id,
                ocr_schema,
                ocr_partition_field,
            )
            print(
                f"[ocr] Tabla BQ asegurada: "
                f"{gcp_config['project_id']}.{gcp_config['dataset_id']}.{ocr_table_id}"
            )
    else:
        print("[ocr] enabled=False (textExtraction deshabilitado o upload_gcs=false)")

    media_lines: dict[tuple[int | None, int | None], dict[str, Any]] = {}
    if chat_messages is not None:
        for msg in chat_messages:
            if is_media_chat_line(msg, filter_cfg):
                key = message_key(msg)
                if key[0] is not None and key[1] is not None:
                    media_lines[key] = msg
        print(f"Líneas de conversación tipo archivo en reporteChats: {len(media_lines)}")
        if match_chats_only and not media_lines:
            print("Sin líneas archivo nuevas; backfill MP3/imágenes/OCR desde documento_raw.")
            mp3_rows: list[dict[str, Any]] = []
            ocr_rows: list[dict[str, Any]] = []
            img_processed_keys: set[tuple[int, int]] = set()
            mp3_converted = 0
            mp3_failed = 0
            img_converted = 0
            img_failed = 0
            ocr_converted = 0
            ocr_failed = 0
            if mp3_enabled and upload_gcs and not force_reprocess:
                mp3_converted, mp3_failed = _backfill_pending_mp3(
                    fecha_evento=fecha_evento,
                    gcp_config=gcp_config,
                    mp3_cfg=mp3_cfg,
                    storage_gcs_path=gcs_path,
                    bq_cfg=bq_cfg,
                    mp3_bq_cfg=mp3_bq_cfg,
                    now=now,
                    existing_mp3_keys=set(),
                    mp3_rows=mp3_rows,
                )
            if img_enabled and upload_gcs and not force_reprocess:
                img_converted, img_failed = _backfill_pending_images(
                    fecha_evento=fecha_evento,
                    gcp_config=gcp_config,
                    img_cfg=img_cfg,
                    storage_gcs_path=gcs_path,
                    bq_cfg=bq_cfg,
                    now=now,
                    existing_image_keys=set(),
                    processed_keys=img_processed_keys,
                )
            if ocr_enabled and upload_gcs and not force_reprocess:
                ocr_converted, ocr_failed = _backfill_pending_ocr(
                    fecha_evento=fecha_evento,
                    gcp_config=gcp_config,
                    ocr_cfg=ocr_cfg,
                    bq_cfg=bq_cfg,
                    ocr_bq_cfg=ocr_bq_cfg,
                    now=now,
                    existing_ocr_keys=set(),
                    ocr_rows=ocr_rows,
                )
            project_id = gcp_config.get("project_id")
            dataset_id = gcp_config.get("dataset_id")
            if project_id and dataset_id:
                bq_client = bigquery.Client(project=project_id)
                if mp3_enabled and mp3_bq_cfg.get("enabled", True) and mp3_rows:
                    mp3_table_id = mp3_bq_cfg.get("table_id", "reporte_whatsapp_mp3")
                    insert_rows(bq_client, dataset_id, mp3_table_id, mp3_rows)
                    print(f"BigQuery MP3 (append): {len(mp3_rows)} filas")
                if ocr_enabled and ocr_bq_cfg.get("enabled", True) and ocr_rows:
                    ocr_table_id = ocr_bq_cfg.get("table_id", "reporte_whatsapp_ocr")
                    insert_rows(bq_client, dataset_id, ocr_table_id, ocr_rows)
                    print(f"BigQuery OCR (append): {len(ocr_rows)} filas")
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
                "img_enabled": img_enabled,
                "img_converted": img_converted,
                "img_failed": img_failed,
                "ocr_enabled": ocr_enabled,
                "ocr_rows": len(ocr_rows),
                "ocr_converted": ocr_converted,
                "ocr_failed": ocr_failed,
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
    ocr_rows: list[dict[str, Any]] = []
    img_processed_keys: set[tuple[int, int]] = set()
    downloaded = 0
    failed = 0
    mp3_converted = 0
    mp3_failed = 0
    img_converted = 0
    img_failed = 0
    ocr_converted = 0
    ocr_failed = 0
    skipped_no_match = 0
    skipped_existing = 0

    existing_media: dict[tuple[int, int], dict[str, Any]] = {}
    existing_mp3: set[tuple[int, int]] = set()
    existing_images: set[tuple[int, int]] = set()
    existing_ocr: set[tuple[int, int]] = set()
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
        if img_enabled:
            existing_images = load_documento_optimized_image_keys(
                bq_probe,
                doc_ref,
                fecha_evento,
                optimized_subfolder=img_cfg.get("gcs_subfolder", "newimages"),
            )
        if ocr_enabled:
            ocr_table = ocr_bq_cfg.get("table_id", "reporte_whatsapp_ocr")
            ocr_ref = f"{project_id}.{dataset_id}.{ocr_table}"
            existing_ocr = load_ocr_keys_done(bq_probe, ocr_ref, fecha_evento)
        print(
            f"[onemarketer-media] Ya en BQ fecha={fecha_evento}: "
            f"{len(existing_media)} docs OK, {len(existing_mp3)} mp3, "
            f"{len(existing_images)} img, {len(existing_ocr)} ocr"
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
                        storage_gcs_path=gcs_path,
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
            prior_image = is_image_for_optimize(
                mime or prior.get("mime"),
                prior.get("file_name"),
                prior.get("media_type") or media_type,
            )
            inc_img_row: dict[str, Any] | None = None
            if (
                img_enabled
                and prior_image
                and key not in existing_images
                and prior.get("gcs_uri")
                and prior.get("file_name")
            ):
                try:
                    inc_img_row = _convert_image_from_gcs_row(
                        prior,
                        gcp_config=gcp_config,
                        img_cfg=img_cfg,
                        fecha_evento=fecha_evento,
                        storage_gcs_path=gcs_path,
                        mime=mime or prior.get("mime"),
                        media_type=prior.get("media_type") or media_type,
                        now=now,
                    )
                    if inc_img_row.get("conversion_status") == "OK":
                        img_converted += 1
                    elif inc_img_row.get("conversion_status") == "FAILED":
                        img_failed += 1
                    img_processed_keys.add(key)
                    _finalize_image_only_storage(
                        gcp_config=gcp_config,
                        img_cfg=img_cfg,
                        bq_cfg=bq_cfg,
                        fecha_evento=fecha_evento,
                        idcase=prior.get("idcase"),
                        idmessage=prior.get("idmessage"),
                        original_gcs_uri=prior.get("gcs_uri"),
                        img_row=inc_img_row,
                    )
                except Exception as exc:
                    print(f"    [img] ✗ desde GCS existente: {exc}")
            needs_ocr = is_ocr_candidate(
                mime or prior.get("mime"),
                prior.get("file_name"),
                prior.get("media_type") or media_type,
            )
            if (
                ocr_enabled
                and needs_ocr
                and key not in existing_ocr
                and prior.get("gcs_uri")
                and prior.get("file_name")
            ):
                try:
                    prior_ocr_ctx = dict(prior)
                    if inc_img_row and _image_opt_success(inc_img_row):
                        prior_ocr_ctx["gcs_uri"] = inc_img_row["gcs_uri"]
                        prior_ocr_ctx["file_name"] = inc_img_row["file_name"]
                        prior_ocr_ctx["optimized_gcs_uri"] = inc_img_row["gcs_uri"]
                    ocr_row = _convert_ocr_from_gcs_row(
                        prior_ocr_ctx,
                        gcp_config=gcp_config,
                        ocr_cfg=ocr_cfg,
                        fecha_evento=fecha_evento,
                        mime=mime or prior.get("mime"),
                        media_type=prior.get("media_type") or media_type,
                        now=now,
                    )
                    ocr_rows.append(ocr_row)
                    if ocr_row.get("ocr_status") == "OK":
                        ocr_converted += 1
                    elif ocr_row.get("ocr_status") == "FAILED":
                        ocr_failed += 1
                except Exception as exc:
                    print(f"    [ocr] ✗ desde GCS existente: {exc}")
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
                should_img = is_image_for_optimize(mime, storage_file_name, media_type)
                img_row: dict[str, Any] | None = None
                store_original = _image_store_original(img_cfg)

                if (
                    img_enabled
                    and should_img
                    and not store_original
                    and key not in existing_images
                ):
                    img_row = convert_whatsapp_image_row(
                        local_source_path=final_path,
                        storage_file_name=storage_file_name,
                        source_file_name=source_file_name,
                        source_gcs_uri=None,
                        gcp_config=gcp_config,
                        img_cfg=img_cfg,
                        fecha_evento=fecha_evento,
                        chat_line=chat_line,
                        mime=mime,
                        media_type=media_type,
                        now=now,
                        tmp_dir=tmp,
                        storage_gcs_path=gcs_path,
                    )
                    if img_row.get("conversion_status") == "OK":
                        img_converted += 1
                    elif img_row.get("conversion_status") == "FAILED":
                        img_failed += 1
                    img_processed_keys.add(key)

                gcs_uri = None
                if upload_gcs:
                    if _image_opt_success(img_row) and not store_original:
                        gcs_uri = img_row["gcs_uri"]
                        print(f"    → {gcs_uri} (solo optimizado)")
                    else:
                        gcs_uri = _upload_blob(
                            final_path, gcp_config, gcs_path, fecha_evento, object_name
                        )
                        print(f"    → {gcs_uri}")
                        if (
                            img_enabled
                            and should_img
                            and store_original
                            and key not in existing_images
                            and img_row is None
                        ):
                            img_row = convert_whatsapp_image_row(
                                local_source_path=final_path,
                                storage_file_name=storage_file_name,
                                source_file_name=source_file_name,
                                source_gcs_uri=gcs_uri,
                                gcp_config=gcp_config,
                                img_cfg=img_cfg,
                                fecha_evento=fecha_evento,
                                chat_line=chat_line,
                                mime=mime,
                                media_type=media_type,
                                now=now,
                                tmp_dir=tmp,
                                storage_gcs_path=gcs_path,
                            )
                            if img_row.get("conversion_status") == "OK":
                                img_converted += 1
                            elif img_row.get("conversion_status") == "FAILED":
                                img_failed += 1
                            img_processed_keys.add(key)
                        elif (
                            img_enabled
                            and should_img
                            and not store_original
                            and img_row is not None
                            and not _image_opt_success(img_row)
                        ):
                            print("    [img] fallback: se conserva original en media/")
                elif storage_cfg.get("save_local_files", True):
                    local_dir = storage_cfg.get("local_dir", "descarga")
                    folder = os.path.join(local_dir, str(idmessage))
                    os.makedirs(folder, exist_ok=True)
                    dest = os.path.join(folder, storage_file_name)
                    with open(final_path, "rb") as src, open(dest, "wb") as dst:
                        dst.write(src.read())
                    print(f"    → local {dest}")

                base_row["source_file_name"] = source_file_name
                if _image_opt_success(img_row) and not store_original:
                    _apply_img_row_to_documento(base_row, img_row, img_cfg)
                else:
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
                        storage_gcs_path=gcs_path,
                    )
                    mp3_rows.append(mp3_row)
                    if mp3_row.get("conversion_status") == "OK":
                        mp3_converted += 1
                    elif mp3_row.get("conversion_status") == "FAILED":
                        mp3_failed += 1

                should_ocr = is_ocr_candidate(mime, storage_file_name, media_type)
                if ocr_enabled and should_ocr and key not in existing_ocr:
                    doc_gcs_uri = base_row.get("gcs_uri") or gcs_uri
                    ocr_row = convert_whatsapp_ocr_row(
                        local_source_path=final_path,
                        storage_file_name=base_row.get("file_name") or storage_file_name,
                        source_file_name=source_file_name,
                        source_gcs_uri=doc_gcs_uri,
                        optimized_gcs_uri=img_row.get("gcs_uri") if _image_opt_success(img_row) else None,
                        gcp_config=gcp_config,
                        ocr_cfg=ocr_cfg,
                        fecha_evento=fecha_evento,
                        chat_line=chat_line,
                        mime=mime,
                        media_type=media_type,
                        now=now,
                    )
                    ocr_rows.append(ocr_row)
                    if ocr_row.get("ocr_status") == "OK":
                        ocr_converted += 1
                    elif ocr_row.get("ocr_status") == "FAILED":
                        ocr_failed += 1
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
            storage_gcs_path=gcs_path,
            bq_cfg=bq_cfg,
            mp3_bq_cfg=mp3_bq_cfg,
            now=now,
            existing_mp3_keys=existing_mp3,
            mp3_rows=mp3_rows,
        )
        mp3_converted += backfill_ok
        mp3_failed += backfill_fail

    if img_enabled and upload_gcs and not force_reprocess:
        backfill_ok, backfill_fail = _backfill_pending_images(
            fecha_evento=fecha_evento,
            gcp_config=gcp_config,
            img_cfg=img_cfg,
            storage_gcs_path=gcs_path,
            bq_cfg=bq_cfg,
            now=now,
            existing_image_keys=existing_images,
            processed_keys=img_processed_keys,
        )
        img_converted += backfill_ok
        img_failed += backfill_fail

    if ocr_enabled and upload_gcs and not force_reprocess:
        backfill_ok, backfill_fail = _backfill_pending_ocr(
            fecha_evento=fecha_evento,
            gcp_config=gcp_config,
            ocr_cfg=ocr_cfg,
            bq_cfg=bq_cfg,
            ocr_bq_cfg=ocr_bq_cfg,
            now=now,
            existing_ocr_keys=existing_ocr,
            ocr_rows=ocr_rows,
        )
        ocr_converted += backfill_ok
        ocr_failed += backfill_fail

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

    if ocr_enabled and ocr_bq_cfg.get("enabled", True) and ocr_rows:
        project_id = gcp_config["project_id"]
        dataset_id = gcp_config["dataset_id"]
        ocr_table_id = ocr_bq_cfg.get("table_id", "reporte_whatsapp_ocr")
        ocr_partition_field = ocr_bq_cfg.get("partition_field", "fecha_evento")

        bq_client = bigquery.Client(project=project_id)
        ocr_schema = load_schema(ocr_table_id)
        ocr_table_ref = ensure_table(
            bq_client, project_id, dataset_id, ocr_table_id, ocr_schema, ocr_partition_field
        )
        if force_reprocess:
            delete_partition(bq_client, ocr_table_ref, fecha_evento, ocr_partition_field)
        insert_rows(bq_client, dataset_id, ocr_table_id, ocr_rows)
        mode = "reemplazo" if force_reprocess else "append"
        print(f"BigQuery OCR ({mode}): {len(ocr_rows)} filas nuevas en {ocr_table_ref}")

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
        "img_enabled": img_enabled,
        "img_converted": img_converted,
        "img_failed": img_failed,
        "ocr_enabled": ocr_enabled,
        "ocr_rows": len(ocr_rows),
        "ocr_converted": ocr_converted,
        "ocr_failed": ocr_failed,
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
