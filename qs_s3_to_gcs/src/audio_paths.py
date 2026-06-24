"""Parseo de nombres AAABBB-YYYYMMDD-correlativo.mp3 y rutas GCS por fecha."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

# Ejemplo: 015AD1-20260217-123728.mp3
#   015     = campus (AAA)
#   AD1     = tipo/código (BBB) — metadata opcional
#   20260217 = fecha en el nombre
#   123728  = correlativo
DEFAULT_FILENAME_REGEX = (
    r"^(?P<campus>[A-Za-z0-9]{3})(?P<type_code>[A-Za-z0-9]{3})-"
    r"(?P<file_date>\d{8})-(?P<correlative>\d+)\.mp3$"
)


def parse_audio_filename(file_name: str, pattern: str) -> dict[str, Any] | None:
    match = re.match(pattern, file_name, re.IGNORECASE)
    if not match:
        return None
    file_date_raw = match.group("file_date")
    try:
        file_date = datetime.strptime(file_date_raw, "%Y%m%d").date()
    except ValueError:
        return None
    return {
        "campus": match.group("campus"),
        "type_code": match.group("type_code"),
        "file_date": file_date,
        "file_date_raw": file_date_raw,
        "correlative": match.group("correlative"),
        "file_name": file_name,
    }


def resolve_sync_mode(sync_cfg: dict[str, Any]) -> str:
    mode = (sync_cfg.get("mode") or "daily_yesterday").strip().lower()
    if mode not in {"backfill_all", "daily_yesterday"}:
        raise ValueError(f"sync.mode inválido: {mode}")
    return mode


def resolve_target_date(sync_cfg: dict[str, Any], mode: str) -> date | None:
    """None en backfill_all; en daily_yesterday devuelve ayer (o SYNC_TARGET_DATE)."""
    if mode == "backfill_all":
        return None

    override = sync_cfg.get("target_date")
    if override:
        return datetime.strptime(str(override), "%Y-%m-%d").date()

    tz_name = sync_cfg.get("timezone", "America/Lima")
    tz = ZoneInfo(tz_name)
    return (datetime.now(tz) - timedelta(days=1)).date()


def gcs_key_for_audio(
    file_name: str,
    file_date: date,
    gcs_prefix: str,
    *,
    date_folder_format: str = "%Y-%m-%d",
) -> str:
    """gs://.../{prefix}/{YYYY-MM-DD}/{file_name}"""
    folder = file_date.strftime(date_folder_format)
    return f"{gcs_prefix.rstrip('/')}/{folder}/{file_name}"


def basename_from_s3_key(s3_key: str) -> str:
    return os.path.basename(s3_key)
