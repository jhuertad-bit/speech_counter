#!/usr/bin/env python3
"""Entry point Cloud Run Job: SQL Server → BigQuery raw_queuesmart."""

from __future__ import annotations

import json
import os
import sys

from config_loader import load_config
from extract import run_extract

CONFIG_PATH = os.environ.get(
    "CONFIG_PATH",
    os.path.join(os.path.dirname(__file__), "config", "config.json"),
)


def main() -> int:
    strict_sql = os.environ.get("SKIP_SQL_VALIDATION", "").lower() not in {"1", "true", "yes"}
    config = load_config(CONFIG_PATH, strict_sql=strict_sql)
    result = run_extract(config)

    summary = {
        "status": "ok" if not result.errors else "partial",
        "mode": result.mode,
        "date_window": result.date_window,
        "sql_rows": result.sql_rows,
        "candidates": result.candidates,
        "inserted": result.inserted,
        "skipped_existing": result.skipped_existing,
        "skipped_date": result.skipped_date,
        "skipped_limit": result.skipped_limit,
        "errors": result.errors,
    }
    print(json.dumps(summary, indent=2))
    return 0 if not result.errors else 1


if __name__ == "__main__":
    sys.exit(main())
