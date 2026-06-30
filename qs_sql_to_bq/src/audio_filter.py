"""Ventana de fechas para filtrar por columna Audio (YYYYMMDD en el nombre)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

AUDIO_DATE_RE = re.compile(r"-(\d{8})-")


def resolve_sync_mode(sync_cfg: dict[str, Any]) -> str:
    mode = (sync_cfg.get("mode") or "daily_yesterday").strip().lower()
    valid = {"backfill_all", "daily_yesterday", "daily_last_n_days"}
    if mode not in valid:
        raise ValueError(f"sync.mode inválido: {mode}")
    return mode


def _lima_today(sync_cfg: dict[str, Any]) -> date:
    tz = ZoneInfo(sync_cfg.get("timezone", "America/Lima"))
    return datetime.now(tz).date()


def resolve_date_window(sync_cfg: dict[str, Any], mode: str) -> tuple[date | None, date | None]:
    if mode == "backfill_all":
        return None, None

    override = sync_cfg.get("target_date")
    if override and mode == "daily_yesterday":
        d = datetime.strptime(str(override), "%Y-%m-%d").date()
        return d, d

    yesterday = _lima_today(sync_cfg) - timedelta(days=1)
    if mode == "daily_yesterday":
        return yesterday, yesterday

    lookback = int(sync_cfg.get("lookback_days", 15))
    start = yesterday - timedelta(days=lookback - 1)
    return start, yesterday


def format_date_window(start: date | None, end: date | None) -> str | None:
    if start is None or end is None:
        return None
    if start == end:
        return start.isoformat()
    return f"{start.isoformat()}..{end.isoformat()}"


def audio_date_from_filename(audio: str | None) -> date | None:
    if not audio:
        return None
    match = AUDIO_DATE_RE.search(audio)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def audio_in_window(audio: str | None, start: date | None, end: date | None) -> bool:
    if start is None and end is None:
        return True
    file_date = audio_date_from_filename(audio)
    if file_date is None:
        return False
    if start is None or end is None:
        return False
    return start <= file_date <= end
