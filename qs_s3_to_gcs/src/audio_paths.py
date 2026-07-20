"""Parseo de nombres AAABBB-YYYYMMDD-correlativo.(mp3|webm|...) y rutas GCS por fecha."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from converter import mp3_file_name

# Ejemplo: 015AD1-20260217-123728.mp3 | 095IX1-20260318-155702.webm
DEFAULT_FILENAME_REGEX = (
    r"^(?P<campus>[A-Za-z0-9]{3})(?P<type_code>[A-Za-z0-9]{3})-"
    r"(?P<file_date>\d{8})-(?P<correlative>\d+)\."
    r"(?P<ext>mp3|webm|ogg|opus|wav|flac|m4a|aac|wma|amr|3gp|mp4)$"
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
    source_file_name = file_name
    return {
        "campus": match.group("campus"),
        "type_code": match.group("type_code"),
        "file_date": file_date,
        "file_date_raw": file_date_raw,
        "correlative": match.group("correlative"),
        "ext": match.group("ext").lower(),
        "source_file_name": source_file_name,
        "file_name": mp3_file_name(source_file_name),
    }


def resolve_sync_mode(sync_cfg: dict[str, Any]) -> str:
    mode = (sync_cfg.get("mode") or "daily_yesterday").strip().lower()
    valid = {"backfill_all", "daily_yesterday", "daily_last_n_days"}
    if mode not in valid:
        raise ValueError(f"sync.mode inválido: {mode} (válidos: {', '.join(sorted(valid))})")
    return mode


def _lima_today(sync_cfg: dict[str, Any]) -> date:
    tz_name = sync_cfg.get("timezone", "America/Lima")
    return datetime.now(ZoneInfo(tz_name)).date()


def resolve_lookback_days(sync_cfg: dict[str, Any]) -> int:
    raw = sync_cfg.get("lookback_days", 15)
    days = int(raw)
    if days < 1:
        raise ValueError("sync.lookback_days debe ser >= 1")
    return days


def resolve_date_window(sync_cfg: dict[str, Any], mode: str) -> tuple[date | None, date | None]:
    """
    Ventana de fechas (inclusive) según fecha en el nombre del archivo.

    - backfill_all: sin filtro (None, None)
    - daily_yesterday: solo ayer (o SYNC_TARGET_DATE)
    - daily_last_n_days: desde ayer hacia atrás N días (default 15)
    """
    if mode == "backfill_all":
        return None, None

    override = sync_cfg.get("target_date")
    if override and mode == "daily_yesterday":
        d = datetime.strptime(str(override), "%Y-%m-%d").date()
        return d, d

    yesterday = _lima_today(sync_cfg) - timedelta(days=1)

    if mode == "daily_yesterday":
        return yesterday, yesterday

    if mode == "daily_last_n_days":
        lookback = resolve_lookback_days(sync_cfg)
        start = yesterday - timedelta(days=lookback - 1)
        return start, yesterday

    return None, None


def resolve_target_date(sync_cfg: dict[str, Any], mode: str) -> date | None:
    """Compat: un solo día (daily_yesterday) o fin de ventana."""
    start, end = resolve_date_window(sync_cfg, mode)
    if start is None and end is None:
        return None
    return end


def format_date_window(start: date | None, end: date | None) -> str | None:
    if start is None or end is None:
        return None
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()}..{end.isoformat()}"


def file_date_in_window(file_date: date, start: date | None, end: date | None) -> bool:
    if start is None and end is None:
        return True
    if start is None or end is None:
        return False
    return start <= file_date <= end


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
