"""Rutas GCS del original y resolución del rango de backfill."""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any


def resolve_date_range(sync_cfg: dict[str, Any]) -> tuple[date, date]:
    start_raw = (sync_cfg.get("start_date") or "").strip()
    end_raw = (sync_cfg.get("end_date") or "").strip()
    if not start_raw or not end_raw:
        raise ValueError(
            "Define BACKFILL_START_DATE y BACKFILL_END_DATE "
            "(o sync.start_date / sync.end_date) como YYYY-MM-DD"
        )
    start = datetime.strptime(start_raw, "%Y-%m-%d").date()
    end = datetime.strptime(end_raw, "%Y-%m-%d").date()
    if end < start:
        raise ValueError(f"end_date ({end}) < start_date ({start})")
    return start, end


def run_id_for_range(start: date, end: date) -> str:
    """Clave del manifiesto (process_date en meta/paths)."""
    return f"{start.isoformat()}_{end.isoformat()}"


def gcs_key_for_original(
    source_file_name: str,
    file_date: date | str,
    gcs_prefix: str,
    *,
    date_folder_format: str = "%Y-%m-%d",
    original_subdir: str = "original",
) -> str:
    if isinstance(file_date, str):
        d = datetime.strptime(file_date[:10], "%Y-%m-%d").date()
    else:
        d = file_date
    folder = d.strftime(date_folder_format)
    name = os.path.basename(str(source_file_name).strip())
    sub = (original_subdir or "original").strip("/").strip() or "original"
    return f"{gcs_prefix.rstrip('/')}/{folder}/{sub}/{name}"


def guess_content_type(file_name: str) -> str:
    ext = os.path.splitext(file_name)[1].lower()
    mapping = {
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".flac": "audio/flac",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".audio": "application/octet-stream",
    }
    return mapping.get(ext, "application/octet-stream")
