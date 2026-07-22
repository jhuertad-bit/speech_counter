"""Manifiesto GCS para Cloud Run Job multi-task (CLOUD_RUN_TASK_INDEX)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from google.cloud import storage


def manifest_paths(gcs_prefix_state: str, process_date: str) -> tuple[str, str]:
    """Retorna (jsonl_key, meta_key) bajo el bucket GCS."""
    base = gcs_prefix_state.rstrip("/")
    return (
        f"{base}/{process_date}.jsonl",
        f"{base}/{process_date}.meta.json",
    )


def write_manifest(
    gcs_client: storage.Client,
    *,
    bucket: str,
    process_date: str,
    items: list[dict[str, Any]],
    manifest_prefix: str,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    jsonl_key, meta_key = manifest_paths(manifest_prefix, process_date)
    blob = gcs_client.bucket(bucket).blob(jsonl_key)
    lines = [json.dumps(item, ensure_ascii=False, default=str) for item in items]
    blob.upload_from_string("\n".join(lines) + ("\n" if lines else ""), content_type="application/x-ndjson")

    meta: dict[str, Any] = {
        "process_date": process_date,
        "count": len(items),
        "manifest_object": jsonl_key,
        "meta_object": meta_key,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if extra_meta:
        meta.update(extra_meta)
    gcs_client.bucket(bucket).blob(meta_key).upload_from_string(
        json.dumps(meta, indent=2, ensure_ascii=False),
        content_type="application/json",
    )
    return meta


def read_manifest_meta(
    gcs_client: storage.Client,
    *,
    bucket: str,
    process_date: str,
    manifest_prefix: str,
) -> dict[str, Any]:
    _, meta_key = manifest_paths(manifest_prefix, process_date)
    blob = gcs_client.bucket(bucket).blob(meta_key)
    if not blob.exists():
        raise FileNotFoundError(f"gs://{bucket}/{meta_key} no existe")
    return json.loads(blob.download_as_text())


def read_manifest_item(
    gcs_client: storage.Client,
    *,
    bucket: str,
    process_date: str,
    manifest_prefix: str,
    task_index: int,
) -> dict[str, Any] | None:
    """Lee la línea task_index del JSONL. None si el índice está fuera de rango."""
    jsonl_key, _ = manifest_paths(manifest_prefix, process_date)
    blob = gcs_client.bucket(bucket).blob(jsonl_key)
    if not blob.exists():
        raise FileNotFoundError(f"gs://{bucket}/{jsonl_key} no existe")
    text = blob.download_as_text()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if task_index < 0 or task_index >= len(lines):
        return None
    return json.loads(lines[task_index])
