"""Rutas GCS alineadas con documento_raw: {base}/{fecha}/{subfolder}/{archivo}."""

from __future__ import annotations

from typing import Any


def resolve_gcs_base(cfg: dict[str, Any], storage_gcs_path: str) -> str:
    base = cfg.get("gcs_base") or storage_gcs_path
    if base:
        return str(base).rstrip("/")
    legacy = str(cfg.get("gcs_path") or "").rstrip("/")
    for suffix in ("/mp3", "/newimages"):
        if legacy.endswith(suffix):
            return legacy[: -len(suffix)]
    return legacy


def dated_subfolder_blob(
    gcs_base: str,
    fecha_evento: str,
    subfolder: str,
    file_name: str,
) -> str:
    return f"{gcs_base.rstrip('/')}/{fecha_evento}/{subfolder.strip('/')}/{file_name}"
