"""Optimización de imágenes WhatsApp/OneMarketer → WebP/AVIF + registro BQ."""

from __future__ import annotations

import os
from typing import Any

from google.cloud import storage

from image_converter import (
    convert_image,
    is_image_for_optimize,
    is_supported_image,
    normalize_extension,
    optimized_file_name,
    output_extension,
)


def _content_type(output_format: str) -> str:
    fmt = (output_format or "webp").lower()
    return "image/avif" if fmt == "avif" else "image/webp"


def _upload_optim_blob(
    local_path: str,
    gcp_config: dict[str, Any],
    gcs_prefix: str,
    fecha_evento: str,
    dest_name: str,
    output_format: str,
) -> str:
    project_id = gcp_config["project_id"]
    bucket_name = gcp_config["bucket_name"]
    blob_name = f"{gcs_prefix.rstrip('/')}/{fecha_evento}/media/{dest_name}"

    client = storage.Client(project=project_id)
    blob = client.bucket(bucket_name).blob(blob_name)
    blob.upload_from_filename(local_path, content_type=_content_type(output_format))
    return f"gs://{bucket_name}/{blob_name}"


def _optim_exists(
    gcp_config: dict[str, Any],
    gcs_prefix: str,
    fecha_evento: str,
    dest_name: str,
) -> bool:
    bucket_name = gcp_config["bucket_name"]
    blob_name = f"{gcs_prefix.rstrip('/')}/{fecha_evento}/media/{dest_name}"
    client = storage.Client(project=gcp_config["project_id"])
    return client.bucket(bucket_name).blob(blob_name).exists()


def convert_whatsapp_image_row(
    *,
    local_source_path: str,
    storage_file_name: str,
    source_file_name: str,
    source_gcs_uri: str | None,
    gcp_config: dict[str, Any],
    img_cfg: dict[str, Any],
    fecha_evento: str,
    chat_line: dict[str, Any],
    mime: str | None,
    media_type: str | None,
    now: str,
    tmp_dir: str,
) -> dict[str, Any]:
    """Convierte imagen, sube a GCS y devuelve fila para reporte_whatsapp_imagen_optimizada."""
    image_settings = img_cfg.get("image", {})
    gcs_optim_path = img_cfg.get("gcs_path", "")
    output_format = (image_settings.get("output_format") or "webp").lower()
    dest_name = optimized_file_name(storage_file_name, output_format)

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
        "file_name": dest_name,
        "output_format": output_format,
        "source_file_size_bytes": None,
        "file_size_bytes": None,
        "quality": image_settings.get("quality"),
        "compression_ratio_pct": None,
        "conversion_method": None,
        "conversion_status": None,
        "error_message": None,
    }

    if not is_image_for_optimize(mime, storage_file_name, media_type):
        base_row["conversion_status"] = "SKIPPED_NOT_IMAGE"
        return base_row

    supported = image_settings.get("supported_extensions", [])
    if not is_supported_image(storage_file_name, supported):
        ext = normalize_extension(storage_file_name)
        if ext == output_extension(output_format):
            if source_gcs_uri:
                base_row["gcs_uri"] = source_gcs_uri
                base_row["file_name"] = storage_file_name
                base_row["file_size_bytes"] = os.path.getsize(local_source_path)
                base_row["conversion_status"] = "SKIPPED_ALREADY_OPTIMIZED"
            return base_row
        base_row["conversion_status"] = "SKIPPED_UNSUPPORTED"
        base_row["error_message"] = f"Extensión no soportada: {storage_file_name}"
        return base_row

    skip_existing = image_settings.get("skip_existing", True)
    if skip_existing and _optim_exists(gcp_config, gcs_optim_path, fecha_evento, dest_name):
        bucket = gcp_config["bucket_name"]
        blob_name = f"{gcs_optim_path.rstrip('/')}/{fecha_evento}/media/{dest_name}"
        base_row["gcs_uri"] = f"gs://{bucket}/{blob_name}"
        base_row["file_name"] = dest_name
        base_row["conversion_status"] = "SKIPPED_EXISTS"
        print(f"    [img] ya existe en GCS: {base_row['gcs_uri']}")
        return base_row

    temp_out = os.path.join(tmp_dir, dest_name)
    try:
        meta = convert_image(local_source_path, temp_out, storage_file_name, image_settings)
        out_size = os.path.getsize(temp_out)
        gcs_uri = _upload_optim_blob(
            temp_out, gcp_config, gcs_optim_path, fecha_evento, dest_name, output_format
        )
        base_row.update(
            {
                "gcs_uri": gcs_uri,
                "file_name": dest_name,
                "source_file_size_bytes": meta.get("source_file_size_bytes"),
                "file_size_bytes": out_size,
                "quality": meta.get("quality"),
                "compression_ratio_pct": meta.get("compression_ratio_pct"),
                "conversion_method": meta.get("method"),
                "conversion_status": "OK",
            }
        )
        print(
            f"    [img] {output_format} → {gcs_uri} "
            f"(-{meta.get('compression_ratio_pct', 0)}% vs original)"
        )
    except ValueError as exc:
        if str(exc) == "ALREADY_OPTIMIZED" and source_gcs_uri:
            base_row["gcs_uri"] = source_gcs_uri
            base_row["file_name"] = storage_file_name
            base_row["file_size_bytes"] = os.path.getsize(local_source_path)
            base_row["conversion_status"] = "SKIPPED_ALREADY_OPTIMIZED"
            print(f"    [img] ya optimizado: {source_gcs_uri}")
        else:
            base_row["conversion_status"] = "SKIPPED_UNSUPPORTED"
            base_row["error_message"] = str(exc)[:500]
            print(f"    [img] omitido: {exc}")
    except Exception as exc:
        base_row["conversion_status"] = "FAILED"
        base_row["error_message"] = str(exc)[:500]
        print(f"    [img] ✗ conversión falló: {exc}")
    finally:
        if os.path.exists(temp_out):
            os.remove(temp_out)

    return base_row
