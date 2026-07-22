"""I/O streaming a disco (evita cargar el audio completo en RAM)."""

from __future__ import annotations

import os
from typing import Any

from google.cloud import storage


def stream_s3_to_file(
    s3_client,
    *,
    bucket: str,
    key: str,
    dest_path: str,
    chunk_size: int = 8 * 1024 * 1024,
) -> int:
    """Descarga S3 → archivo local por chunks. Retorna bytes escritos."""
    response = s3_client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    written = 0
    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    with open(dest_path, "wb") as handle:
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                break
            handle.write(chunk)
            written += len(chunk)
    if written == 0:
        raise ValueError("archivo vacío en S3")
    return written


def stream_file_to_gcs(
    gcs_client: storage.Client,
    *,
    local_path: str,
    bucket: str,
    blob_name: str,
    content_type: str,
    chunk_size: int = 8 * 1024 * 1024,
) -> int:
    """Sube archivo local → GCS por chunks (resumable). Retorna tamaño."""
    size = os.path.getsize(local_path)
    blob = gcs_client.bucket(bucket).blob(blob_name)
    blob.chunk_size = chunk_size
    blob.upload_from_filename(local_path, content_type=content_type)
    return size


def copy_file(src: str, dest: str, *, chunk_size: int = 8 * 1024 * 1024) -> int:
    written = 0
    with open(src, "rb") as rin, open(dest, "wb") as rout:
        while True:
            chunk = rin.read(chunk_size)
            if not chunk:
                break
            rout.write(chunk)
            written += len(chunk)
    return written
