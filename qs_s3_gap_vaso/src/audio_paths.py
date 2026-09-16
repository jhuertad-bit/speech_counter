"""Parseo de nombres Ticketero: {prefijo}-{YYYYMMDD}-{correlativo}.ext y rutas GCS."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from converter import mp3_file_name

# Formato Ticketero: tres segmentos separados por guión + extensión de audio.
ALLOWED_EXTENSIONS = frozenset({
    "mp3", "webm", "ogg", "opus", "wav", "flac", "m4a", "aac",
    "wma", "amr", "3gp", "mp4", "audio",
})

# Regex legado (config antigua); preferir parseo por guiones.
LEGACY_FILENAME_REGEX = (
    r"^(?P<campus>[A-Za-z0-9]{3})(?P<type_code>[A-Za-z0-9]{3})-"
    r"(?P<file_date>\d{8})-(?P<correlative>\d+)\."
    r"(?P<ext>mp3|webm|ogg|opus|wav|flac|m4a|aac|wma|amr|3gp|mp4|audio)$"
)


def split_campus_type_code(prefix: str) -> tuple[str, str] | None:
    """
    Deriva campus (3) y type_code (resto) del primer segmento (antes del 1er `-`).

    - 5 chars: falta cero a la izquierda (65AG6 → 065, AG6)
    - 4+ chars: campus = primeros 3, tipo = resto (6→3+3, 7→3+4, etc.)
    """
    token = prefix.strip().upper()
    if not token.isalnum() or len(token) < 4:
        return None
    if len(token) == 5:
        padded = f"0{token}"
        return padded[:3], padded[3:6]
    return token[:3], token[3:]


def _parse_by_dashes(file_name: str) -> dict[str, Any] | None:
    """Valida estructura `{prefijo}-{YYYYMMDD}-{correlativo}.ext` por segmentos."""
    name = os.path.basename(file_name.strip())
    if not name or "." not in name:
        return None

    stem, dot, ext = name.rpartition(".")
    ext_lower = ext.lower()
    if not dot or ext_lower not in ALLOWED_EXTENSIONS:
        return None

    parts = stem.split("-")
    if len(parts) != 3:
        return None

    prefix, file_date_raw, correlative = parts
    if not prefix or not prefix.isalnum():
        return None
    if not re.fullmatch(r"\d{8}", file_date_raw):
        return None
    if not correlative or not correlative.isdigit():
        return None

    try:
        file_date = datetime.strptime(file_date_raw, "%Y%m%d").date()
    except ValueError:
        return None

    split = split_campus_type_code(prefix)
    if not split:
        return None
    campus, type_code = split

    return {
        "campus": campus,
        "type_code": type_code,
        "prefix": prefix.upper(),
        "file_date": file_date,
        "file_date_raw": file_date_raw,
        "correlative": correlative,
        "ext": ext_lower,
        "source_file_name": name,
        "file_name": mp3_file_name(name),
    }


def _parse_by_regex(file_name: str, pattern: str) -> dict[str, Any] | None:
    match = re.match(pattern, file_name, re.IGNORECASE)
    if not match:
        return None
    file_date_raw = match.group("file_date")
    try:
        file_date = datetime.strptime(file_date_raw, "%Y%m%d").date()
    except ValueError:
        return None

    groups = match.groupdict()
    if groups.get("prefix"):
        split = split_campus_type_code(groups["prefix"])
    elif groups.get("campus") and groups.get("type_code"):
        split = groups["campus"].upper(), groups["type_code"].upper()
    else:
        return None
    if not split:
        return None
    campus, type_code = split

    ext = groups.get("ext")
    if not ext:
        ext = os.path.splitext(file_name)[1].lstrip(".")
    if ext.lower() not in ALLOWED_EXTENSIONS:
        return None

    return {
        "campus": campus,
        "type_code": type_code,
        "prefix": groups.get("prefix", f"{campus}{type_code}").upper(),
        "file_date": file_date,
        "file_date_raw": file_date_raw,
        "correlative": match.group("correlative"),
        "ext": ext.lower(),
        "source_file_name": file_name,
        "file_name": mp3_file_name(file_name),
    }


def parse_audio_filename(file_name: str, pattern: str | None = None) -> dict[str, Any] | None:
    """
    Parsea nombre Ticketero.

    Por defecto usa segmentos entre `-` (sin límite de longitud del prefijo).
    Si `pattern` está definido en config, usa regex legado.
    """
    if pattern:
        return _parse_by_regex(file_name, pattern)
    return _parse_by_dashes(file_name)


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
