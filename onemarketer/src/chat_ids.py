"""Normalización de idcase/idmessage entre APIs OneMarketer y tablas BQ."""

from __future__ import annotations

import os
import re
from typing import Any

_IDCASE_ALIASES = ("idCase", "IdCase", "id_case", "idcaso")
_IDMESSAGE_ALIASES = (
    "idMessage",
    "IdMessage",
    "id_mensaje",
    "idmensaje",
    "message_id",
    "id_msg",
)


def coerce_int_id(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_ids_from_storage_name(file_name: str | None) -> tuple[int | None, int | None]:
    """Extrae idcase/idmessage de nombres tipo ``12345_67890_audio.ogg``."""
    if not file_name:
        return None, None
    base = os.path.basename(file_name)
    match = re.match(r"^(\d+)_(\d+)_", base)
    if not match:
        return None, None
    return coerce_int_id(match.group(1)), coerce_int_id(match.group(2))


def normalize_message_record(record: dict[str, Any]) -> dict[str, Any]:
    """Unifica alias de API y coerce a int."""
    out = dict(record)
    if out.get("idmessage") is None:
        for alias in _IDMESSAGE_ALIASES:
            if out.get(alias) is not None:
                out["idmessage"] = out[alias]
                break
    if out.get("idcase") is None:
        for alias in _IDCASE_ALIASES:
            if out.get(alias) is not None:
                out["idcase"] = out[alias]
                break
    out["idcase"] = coerce_int_id(out.get("idcase"))
    out["idmessage"] = coerce_int_id(out.get("idmessage"))
    return out


def resolve_chat_ids(
    *records: dict[str, Any] | None,
    key: tuple[int | None, int | None] | None = None,
    file_name: str | None = None,
) -> dict[str, Any]:
    """Resuelve idcase/idmessage desde registros, tupla key y/o nombre de archivo GCS."""
    merged: dict[str, Any] = {}
    for record in records:
        if record:
            merged.update(normalize_message_record(record))
    if key:
        if merged.get("idcase") is None and key[0] is not None:
            merged["idcase"] = key[0]
        if merged.get("idmessage") is None and key[1] is not None:
            merged["idmessage"] = key[1]
    parsed_case, parsed_message = parse_ids_from_storage_name(file_name)
    if merged.get("idcase") is None:
        merged["idcase"] = parsed_case
    if merged.get("idmessage") is None:
        merged["idmessage"] = parsed_message
    merged["idcase"] = coerce_int_id(merged.get("idcase"))
    merged["idmessage"] = coerce_int_id(merged.get("idmessage"))
    return merged


def enrich_media_row(row: dict[str, Any]) -> dict[str, Any]:
    """Completa idcase/idmessage en filas BQ usando alias y nombre de archivo GCS."""
    file_name = row.get("file_name") or row.get("source_file_name")
    ids = resolve_chat_ids(row, file_name=file_name)
    out = dict(row)
    out["idcase"] = ids["idcase"]
    out["idmessage"] = ids["idmessage"]
    return out
