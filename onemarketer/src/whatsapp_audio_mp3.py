"""Conversión de audios WhatsApp/OneMarketer a MP3 (misma lógica que audio_to_mp3)."""

from __future__ import annotations

import os
from typing import Any

from converter import convert_audio_to_mp3, is_supported_audio, normalize_extension
from google.cloud import storage


def mp3_file_name(storage_file_name: str) -> str:
    base, _ = os.path.splitext(storage_file_name)
    return f"{base}.mp3"


def _upload_mp3_blob(
    local_mp3_path: str,
    gcp_config: dict[str, Any],
    gcs_prefix: str,
    fecha_evento: str,
    mp3_name: str,
) -> str:
    project_id = gcp_config["project_id"]
    bucket_name = gcp_config["bucket_name"]
    blob_name = f"{gcs_prefix.rstrip('/')}/{fecha_evento}/media/{mp3_name}"

    client = storage.Client(project=project_id)
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(local_mp3_path, content_type="audio/mpeg")
    return f"gs://{bucket_name}/{blob_name}"


def _mp3_exists(gcp_config: dict[str, Any], gcs_prefix: str, fecha_evento: str, mp3_name: str) -> bool:
    bucket_name = gcp_config["bucket_name"]
    blob_name = f"{gcs_prefix.rstrip('/')}/{fecha_evento}/media/{mp3_name}"
    client = storage.Client(project=gcp_config["project_id"])
    return client.bucket(bucket_name).blob(blob_name).exists()


def convert_whatsapp_audio_row(
    *,
    local_source_path: str,
    storage_file_name: str,
    source_file_name: str,
    source_gcs_uri: str | None,
    gcp_config: dict[str, Any],
    mp3_cfg: dict[str, Any],
    fecha_evento: str,
    chat_line: dict[str, Any],
    mime: str | None,
    now: str,
    tmp_dir: str,
) -> dict[str, Any]:
    """
    Convierte un audio descargado a MP3, sube a GCS y devuelve fila para reporte_whatsapp_mp3.
    """
    audio_cfg = mp3_cfg.get("audio", {})
    gcs_mp3_path = mp3_cfg.get("gcs_path", "")
    mp3_name = mp3_file_name(storage_file_name)

    base_row: dict[str, Any] = {
        "fecha_evento": fecha_evento,
        "fecha_procesamiento": now,
        "idcase": chat_line.get("idcase"),
        "idmessage": chat_line.get("idmessage"),
        "waid": chat_line.get("waid"),
        "mime": mime,
        "source_gcs_uri": source_gcs_uri,
        "source_file_name": source_file_name,
        "gcs_uri": None,
        "file_name": mp3_name,
        "file_size_bytes": None,
        "conversion_method": None,
        "source_codec": None,
        "bitrate": None,
        "duration_seconds": None,
        "conversion_status": None,
        "error_message": None,
    }

    supported = audio_cfg.get("supported_extensions", [])
    if not is_supported_audio(storage_file_name, supported):
        base_row["conversion_status"] = "SKIPPED_UNSUPPORTED"
        base_row["error_message"] = f"Extensión no soportada: {storage_file_name}"
        return base_row

    ext = normalize_extension(storage_file_name)
    skip_existing = audio_cfg.get("skip_existing_mp3", True)

    if skip_existing and _mp3_exists(gcp_config, gcs_mp3_path, fecha_evento, mp3_name):
        bucket = gcp_config["bucket_name"]
        blob_name = f"{gcs_mp3_path.rstrip('/')}/{fecha_evento}/media/{mp3_name}"
        base_row["gcs_uri"] = f"gs://{bucket}/{blob_name}"
        base_row["file_name"] = mp3_name
        base_row["conversion_status"] = "SKIPPED_EXISTS"
        print(f"    [mp3] ya existe en GCS: {base_row['gcs_uri']}")
        return base_row

    # Ya es MP3: registrar apuntando al raw (o re-subir a ruta mp3)
    if ext == ".mp3":
        if source_gcs_uri:
            base_row["gcs_uri"] = source_gcs_uri
            base_row["file_name"] = storage_file_name
            base_row["file_size_bytes"] = os.path.getsize(local_source_path)
            base_row["conversion_status"] = "SKIPPED_ALREADY_MP3"
            print(f"    [mp3] ya es MP3: {source_gcs_uri}")
        return base_row

    temp_mp3 = os.path.join(tmp_dir, mp3_name)
    try:
        meta = convert_audio_to_mp3(
            local_source_path, temp_mp3, storage_file_name, audio_cfg
        )
        mp3_size = os.path.getsize(temp_mp3)
        gcs_uri = _upload_mp3_blob(
            temp_mp3, gcp_config, gcs_mp3_path, fecha_evento, mp3_name
        )
        base_row.update(
            {
                "gcs_uri": gcs_uri,
                "file_name": mp3_name,
                "file_size_bytes": mp3_size,
                "conversion_method": meta.get("method"),
                "source_codec": meta.get("source_codec"),
                "bitrate": meta.get("bitrate"),
                "duration_seconds": meta.get("duration_seconds"),
                "conversion_status": "OK",
            }
        )
        print(f"    [mp3] convertido → {gcs_uri} ({meta.get('method')})")
    except Exception as exc:
        base_row["conversion_status"] = "FAILED"
        base_row["error_message"] = str(exc)[:500]
        print(f"    [mp3] ✗ conversión falló: {exc}")
    finally:
        if os.path.exists(temp_mp3):
            os.remove(temp_mp3)

    return base_row
