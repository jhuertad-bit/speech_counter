#!/usr/bin/env python3
"""
Entry point para Cloud Run Job o ejecución local del micro-batch S3 -> GCS.

Flujo:
  1) Traer audios + convertir MP3/loudnorm + catalogar
  2) Si orchestration.call_consolidate_after_sync: CALL consolidate
     (consolidate a su vez llama a Gen IA)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from bq_procedures import call_procedure
from config_loader import load_config
from sync import run_micro_batch

CONFIG_PATH = os.environ.get(
    "CONFIG_PATH",
    os.path.join(os.path.dirname(__file__), "config", "config.json"),
)


def _resolve_process_date(config: dict, result) -> date:
    if result.process_date is not None:
        return result.process_date
    tz_name = config.get("sync", {}).get("timezone", "America/Lima")
    return datetime.now(ZoneInfo(tz_name)).date() - timedelta(days=1)


def _call_consolidate(config: dict, process_date: date) -> None:
    orch = config.get("orchestration", {})
    project_id = config["gcp"]["project_id"]
    location = orch.get("bq_location") or config.get("bigquery", {}).get("location", "US")
    procedure = orch.get(
        "consolidate_procedure",
        f"{project_id}.raw_queue_smart.sp_queuesmart_mp3_consolidate",
    )
    if procedure.count(".") == 1:
        procedure = f"{project_id}.{procedure}"

    print(f"[orchestration] CALL `{procedure}`({process_date.isoformat()}) location={location}")
    call_procedure(
        project_id=project_id,
        procedure_id=procedure,
        args=[process_date],
        location=location,
    )
    print("[orchestration] consolidate OK")


def main() -> int:
    config = load_config(CONFIG_PATH)
    result = run_micro_batch(config)

    orch = config.get("orchestration", {})
    consolidate_ok = None
    consolidate_error = None

    should_call = bool(orch.get("call_consolidate_after_sync", False))
    skip_on_errors = bool(orch.get("skip_consolidate_on_sync_errors", True))
    only_if_new = bool(orch.get("consolidate_only_if_new", True))
    if should_call and result.errors and skip_on_errors:
        print("[orchestration] omitiendo consolidate por errores en sync")
        should_call = False
    # Evita re-correr Gen IA cada N horas si no hubo MP3 nuevos ni inserts a catálogo
    if should_call and only_if_new and result.copied == 0 and result.bq_inserted == 0:
        print(
            "[orchestration] omitiendo consolidate: sin archivos nuevos "
            f"(copied={result.copied}, bq_inserted={result.bq_inserted})"
        )
        should_call = False

    if should_call:
        try:
            process_date = _resolve_process_date(config, result)
            _call_consolidate(config, process_date)
            consolidate_ok = True
        except Exception as exc:  # noqa: BLE001
            consolidate_ok = False
            consolidate_error = f"{type(exc).__name__}: {exc}"
            print(f"[orchestration] ERROR consolidate: {consolidate_error}")
            result.errors.append(f"consolidate: {consolidate_error}")

    summary = {
        "status": "ok" if not result.errors else "partial",
        "mode": result.mode,
        "target_date": result.target_date,
        "process_date": result.process_date.isoformat() if result.process_date else None,
        "scanned": result.scanned,
        "copied": result.copied,
        "skipped": result.skipped,
        "already_in_gcs": result.already_in_gcs,
        "bq_cataloged": result.bq_cataloged,
        "bq_inserted": result.bq_inserted,
        "bytes_copied": result.bytes_copied,
        "skipped_corrupt": result.skipped_corrupt,
        "unconvertible_new": result.unconvertible_new or [],
        "watermark_before": result.watermark_before,
        "watermark_after": result.watermark_after,
        "consolidate_called": should_call,
        "consolidate_ok": consolidate_ok,
        "consolidate_error": consolidate_error,
        "errors": result.errors,
    }
    print(json.dumps(summary, indent=2))

    return 0 if not result.errors else 1


if __name__ == "__main__":
    sys.exit(main())
