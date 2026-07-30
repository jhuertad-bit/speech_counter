#!/usr/bin/env python3
"""
Cloud Run Job — QueeSmart STT Chirp 3 + diarización (prepare | worker).

Roles (env QS_JOB_ROLE):
  prepare  → URIs del día desde BQ enriched → manifiesto JSONL + meta en GCS
  worker   → CLOUD_RUN_TASK_INDEX toma 1 línea, BatchRecognize, escribe hist BQ

Orquestación: Cloud Workflows (después de consolidate, antes de analisis Gemini).
"""

from __future__ import annotations

import os
import sys
from typing import Any

from config_loader import load_config
from prepare import run_prepare
from worker import run_worker

CONFIG_PATH = os.environ.get(
    "CONFIG_PATH",
    os.path.join(os.path.dirname(__file__), "config", "config.json"),
)


def _resolve_role(config: dict[str, Any]) -> str:
    role = (
        os.environ.get("QS_JOB_ROLE")
        or config.get("job", {}).get("role")
        or "worker"
    ).strip().lower()
    if role not in {"prepare", "worker"}:
        raise ValueError(f"QS_JOB_ROLE inválido: {role} (prepare|worker)")
    return role


def main() -> int:
    config = load_config(CONFIG_PATH)
    role = _resolve_role(config)
    print(f"[qsmart_transcribe] role={role}")

    if role == "prepare":
        run_prepare(config)
        return 0

    return run_worker(config)


if __name__ == "__main__":
    sys.exit(main())
