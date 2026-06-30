#!/usr/bin/env python3
"""
Entry point para Cloud Run Job o ejecución local del micro-batch S3 -> GCS.
"""

from __future__ import annotations

import json
import os
import sys

from config_loader import load_config
from sync import run_micro_batch

CONFIG_PATH = os.environ.get(
    "CONFIG_PATH",
    os.path.join(os.path.dirname(__file__), "config", "config.json"),
)


def main() -> int:
    config = load_config(CONFIG_PATH)
    result = run_micro_batch(config)

    summary = {
        "status": "ok" if not result.errors else "partial",
        "mode": result.mode,
        "target_date": result.target_date,
        "scanned": result.scanned,
        "copied": result.copied,
        "skipped": result.skipped,
        "already_in_gcs": result.already_in_gcs,
        "bq_cataloged": result.bq_cataloged,
        "bq_inserted": result.bq_inserted,
        "bytes_copied": result.bytes_copied,
        "watermark_before": result.watermark_before,
        "watermark_after": result.watermark_after,
        "errors": result.errors,
    }
    print(json.dumps(summary, indent=2))

    return 0 if not result.errors else 1


if __name__ == "__main__":
    sys.exit(main())
