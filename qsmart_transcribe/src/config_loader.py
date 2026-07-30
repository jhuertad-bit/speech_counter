"""Carga config JSON + overrides por env."""

from __future__ import annotations

import json
import os
from typing import Any


def load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def process_date_from_env(config: dict[str, Any]) -> str:
    override = (
        os.environ.get("SYNC_PROCESS_DATE")
        or os.environ.get("SYNC_TARGET_DATE")
        or config.get("sync", {}).get("target_date")
    )
    if not override:
        raise ValueError("Falta SYNC_PROCESS_DATE (YYYY-MM-DD)")
    return str(override).strip()
