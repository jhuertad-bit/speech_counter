#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cloud Run Job — backfill histórico reporteAtenciones (lead/lcra_* desde 2026-06-29).

Env:
  BACKFILL_START_DATE  YYYY-MM-DD (default 2026-06-29)
  BACKFILL_END_DATE    YYYY-MM-DD (default hoy America/Lima)
  BACKFILL_TABLES      csv (default reporteAtenciones)
  STOP_ON_ERROR        1|0 (default 0 — sigue con el siguiente día)

Reusa process_date / normalize_reporte_atenciones_lcra de onemarketer-api (main.py).
Carpeta separada de onemarketer-api para no redesplegar el servicio HTTP en cada build.

Rebuild bump 2026-11-12h: schema PRD exacto (STRING + DATETIME REQUIRED).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import pytz

from gcp_runtime_log import print_runtime_gcp_info
from main import generate_date_range, load_config, process_date


DEFAULT_START = "2026-06-29"
DEFAULT_TABLES = "reporteAtenciones"
LIMA = pytz.timezone("America/Lima")


def _today_lima() -> str:
    return datetime.now(LIMA).strftime("%Y-%m-%d")


def _parse_bool(raw: str, default: bool = False) -> bool:
    v = (raw or "").strip().lower()
    if not v:
        return default
    return v in {"1", "true", "yes", "y", "si", "sí"}


def main() -> int:
    start = os.environ.get("BACKFILL_START_DATE", DEFAULT_START).strip() or DEFAULT_START
    end = os.environ.get("BACKFILL_END_DATE", "").strip() or _today_lima()
    tables_raw = os.environ.get("BACKFILL_TABLES", DEFAULT_TABLES).strip() or DEFAULT_TABLES
    stop_on_error = _parse_bool(os.environ.get("STOP_ON_ERROR", "0"), default=False)
    tables = {t.strip() for t in tables_raw.split(",") if t.strip()}

    try:
        datetime.strptime(start, "%Y-%m-%d")
        datetime.strptime(end, "%Y-%m-%d")
    except ValueError as exc:
        print(f"❌ Fechas inválidas start={start} end={end}: {exc}")
        return 1

    dates = generate_date_range(start, end)
    print("=" * 60)
    print("Cloud Run Job — onemarketer_api_backfill (lcra_*)")
    print(f"Rango: {dates[0]} → {dates[-1]} ({len(dates)} días)")
    print(f"Tablas: {sorted(tables)}")
    print(f"STOP_ON_ERROR={stop_on_error}")
    print("=" * 60)

    os.environ["BACKFILL_TABLES"] = ",".join(sorted(tables))

    runtime_config = load_config("config/config.json")
    print_runtime_gcp_info(runtime_config, service_label="onemarketer_api_backfill")
    print("[onemarketer_api_backfill] OAuth: ONEMARKETER_API_CREDENTIALS")

    successful = 0
    failed = 0
    results = []

    for i, fecha in enumerate(dates, 1):
        print(f"\n[{i}/{len(dates)}] {fecha}")
        ok = process_date(fecha, tables_filter=tables)
        if ok:
            successful += 1
            results.append({"fecha": fecha, "status": "success"})
        else:
            failed += 1
            results.append({"fecha": fecha, "status": "failed"})
            if stop_on_error:
                print("❌ STOP_ON_ERROR=1 — abortando backfill")
                break

    summary = {
        "status": "success" if failed == 0 else "partial_success",
        "start": start,
        "end": end,
        "total_dates": len(dates),
        "successful": successful,
        "failed": failed,
        "results": results,
    }
    print("\n" + "=" * 60)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("=" * 60)

    if successful == 0 and failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
