#!/usr/bin/env python3
"""
Cloud Run Job — backfill one-shot: originales S3 → GCS + UPDATE catálogo.

Roles (JOB_ROLE / QS_JOB_ROLE):
  prepare  → BQ filas sin gcs_original_path en rango → manifiesto GCS
  worker   → CLOUD_RUN_TASK_INDEX copia 1 original y actualiza BQ

Rango: BACKFILL_START_DATE + BACKFILL_END_DATE (YYYY-MM-DD).
Manifiesto: state/manifests_originals_backfill/{start}_{end}.jsonl
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from google.cloud import storage

from config_loader import load_config
from manifest import read_manifest_item, read_manifest_meta
from paths import resolve_date_range, run_id_for_range
from prepare import run_prepare
from worker import build_s3_client, process_one

CONFIG_PATH = os.environ.get(
    "CONFIG_PATH",
    os.path.join(os.path.dirname(__file__), "config", "config.json"),
)


def _resolve_role(config: dict[str, Any]) -> str:
    role = (
        os.environ.get("JOB_ROLE")
        or os.environ.get("QS_JOB_ROLE")
        or config.get("job", {}).get("role")
        or "worker"
    ).strip().lower()
    if role not in {"prepare", "worker"}:
        raise ValueError(f"JOB_ROLE inválido: {role} (prepare|worker)")
    return role


def _process_date(config: dict[str, Any]) -> str:
    override = os.environ.get("SYNC_PROCESS_DATE", "").strip()
    if override:
        return override
    start, end = resolve_date_range(config.get("sync", {}))
    return run_id_for_range(start, end)


def run_worker(config: dict[str, Any]) -> int:
    gcp = config["gcp"]
    aws = config["aws"]
    secrets = config.get("secrets", {})
    job_cfg = config.get("job", {})

    task_index = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
    task_count = int(os.environ.get("CLOUD_RUN_TASK_COUNT", "1"))
    process_date = _process_date(config)
    manifest_prefix = job_cfg.get("manifest_prefix", "state/manifests_originals_backfill")

    print(
        f"[worker] task_index={task_index}/{task_count} process_date={process_date}"
    )

    gcs_client = storage.Client(project=gcp.get("project_id"))
    gcs_bucket = gcp["bucket_name"]

    meta = read_manifest_meta(
        gcs_client,
        bucket=gcs_bucket,
        process_date=process_date,
        manifest_prefix=manifest_prefix,
    )
    manifest_count = int(meta.get("count") or 0)
    if manifest_count == 0:
        print("[worker] manifiesto vacío")
        print(json.dumps({"role": "worker", "status": "ok", "result": "empty_manifest"}))
        return 0
    if task_index >= manifest_count:
        print(f"[worker] task_index={task_index} >= count={manifest_count} — no-op")
        return 0

    item = read_manifest_item(
        gcs_client,
        bucket=gcs_bucket,
        process_date=process_date,
        manifest_prefix=manifest_prefix,
        task_index=task_index,
    )
    if item is None:
        print(f"[worker] sin ítem index={task_index}")
        return 0

    s3_client = build_s3_client(aws, secrets)
    try:
        outcome = process_one(
            config=config,
            s3_client=s3_client,
            gcs_client=gcs_client,
            item=item,
        )
        summary = {
            "role": "worker",
            "status": outcome.get("status", "ok"),
            "task_index": task_index,
            "manifest_count": manifest_count,
            **outcome,
        }
        print(json.dumps(summary, indent=2, default=str))
        return 0 if outcome.get("status") != "error" else 1
    except Exception as exc:  # noqa: BLE001
        msg = f"{item.get('s3_key')}: {type(exc).__name__}: {exc}"
        print(f"[worker] ERROR {msg}")
        print(
            json.dumps(
                {
                    "role": "worker",
                    "status": "error",
                    "task_index": task_index,
                    "s3_key": item.get("s3_key"),
                    "error": msg,
                }
            )
        )
        return 1


def main() -> int:
    config = load_config(CONFIG_PATH)
    role = _resolve_role(config)
    print(f"[qs_s3_originals_backfill] role={role}")
    if role == "prepare":
        run_prepare(config)
        return 0
    return run_worker(config)


if __name__ == "__main__":
    sys.exit(main())
