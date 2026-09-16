"""Utilidades gap VASO (sin dependencias GCP)."""

from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

GAP_SYNC_MODE = "gap_fill"

# Prefijo Ticketero del regex legado: exactamente 3+3 = 6 chars
LEGACY_PREFIX_LEN = 6


def resolve_gap_target_date(config: dict[str, Any]) -> date:
    raw = (
        os.environ.get("GAP_TARGET_DATE")
        or os.environ.get("SYNC_TARGET_DATE")
        or config.get("gap", {}).get("target_date")
    )
    if not raw:
        raise ValueError(
            "GAP_TARGET_DATE requerido (YYYY-MM-DD). Ej.: GAP_TARGET_DATE=2026-09-07"
        )
    return datetime.strptime(str(raw).strip(), "%Y-%m-%d").date()


def is_legacy_miss(parsed: dict[str, Any]) -> bool:
    """
    True si el ingest legado lo habría rechazado:
      - extensión .audio, o
      - prefijo Ticketero con longitud distinta de 6.
    """
    ext = str(parsed.get("ext") or "").lower()
    if ext == "audio":
        return True
    prefix = str(parsed.get("prefix") or "")
    return len(prefix) != LEGACY_PREFIX_LEN
