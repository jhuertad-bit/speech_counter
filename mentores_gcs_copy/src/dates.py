"""Fechas de proceso (America/Lima) y prefijos GCS por carpeta-día."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo


def lima_today(tz_name: str = "America/Lima") -> date:
    return datetime.now(ZoneInfo(tz_name)).date()


def resolve_process_date(config: dict[str, Any]) -> str:
    override = (
        os.environ.get("SYNC_PROCESS_DATE")
        or os.environ.get("SYNC_TARGET_DATE")
        or config.get("sync", {}).get("target_date")
    )
    if override:
        return str(override).strip()
    tz_name = config.get("sync", {}).get("timezone", "America/Lima")
    mode = str(config.get("sync", {}).get("mode") or "daily_yesterday").strip().lower()
    today = lima_today(tz_name)
    if mode == "daily_yesterday":
        return (today - timedelta(days=1)).isoformat()
    return today.isoformat()


def source_list_prefix(source_prefix: str, process_date: str, sync_cfg: dict[str, Any]) -> str:
    """Prefijo a listar en el bucket origen."""
    base = (source_prefix or "").strip().strip("/")
    layout = str(sync_cfg.get("layout") or "date_folder").strip().lower()
    mode = str(sync_cfg.get("mode") or "daily_yesterday").strip().lower()
    if layout == "flat" or mode == "backfill_all":
        return f"{base}/" if base else ""
    fmt = str(sync_cfg.get("gcs_date_folder_format") or "%Y-%m-%d")
    folder = date.fromisoformat(process_date).strftime(fmt)
    if base:
        return f"{base}/{folder}/"
    return f"{folder}/"


def dest_object_name(source_key: str, source_cfg_prefix: str, dest_prefix: str) -> str:
    """Espejo del path relativo al prefix de config (no al prefix listado del día)."""
    rel = source_key.lstrip("/")
    cfg_prefix = (source_cfg_prefix or "").strip().strip("/")
    if cfg_prefix:
        lead = f"{cfg_prefix}/"
        if rel.startswith(lead):
            rel = rel[len(lead) :]
    dest_base = (dest_prefix or "").strip().strip("/")
    if dest_base:
        return f"{dest_base}/{rel}"
    return rel
