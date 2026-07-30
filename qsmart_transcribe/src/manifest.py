"""Manifiesto JSONL + meta en GCS (mismo patrón que qs_s3_to_gcs)."""

from __future__ import annotations

import json
from typing import Any

from google.cloud import storage


def _paths(manifest_prefix: str, process_date: str) -> tuple[str, str]:
    base = f"{manifest_prefix.rstrip('/')}/{process_date}"
    return f"{base}.jsonl", f"{base}.meta.json"


def write_manifest(
    gcs: storage.Client,
    *,
    bucket: str,
    process_date: str,
    manifest_prefix: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    jsonl_path, meta_path = _paths(manifest_prefix, process_date)
    b = gcs.bucket(bucket)

    body = "\n".join(json.dumps(it, ensure_ascii=False, default=str) for it in items)
    if body:
        body += "\n"
    b.blob(jsonl_path).upload_from_string(body, content_type="application/x-ndjson")

    meta = {
        "process_date": process_date,
        "count": len(items),
        "manifest_object": jsonl_path,
    }
    b.blob(meta_path).upload_from_string(
        json.dumps(meta, indent=2),
        content_type="application/json",
    )
    return meta


def read_manifest_meta(
    gcs: storage.Client,
    *,
    bucket: str,
    process_date: str,
    manifest_prefix: str,
) -> dict[str, Any]:
    _, meta_path = _paths(manifest_prefix, process_date)
    raw = gcs.bucket(bucket).blob(meta_path).download_as_text()
    return json.loads(raw)


def read_manifest_item(
    gcs: storage.Client,
    *,
    bucket: str,
    process_date: str,
    manifest_prefix: str,
    task_index: int,
) -> dict[str, Any] | None:
    jsonl_path, _ = _paths(manifest_prefix, process_date)
    text = gcs.bucket(bucket).blob(jsonl_path).download_as_text()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if task_index < 0 or task_index >= len(lines):
        return None
    return json.loads(lines[task_index])
