#!/usr/bin/env python3
"""
Cloud Run Job — Promotores GCS→GCS (prepare | worker) entre proyectos.

Roles (JOB_ROLE o QS_JOB_ROLE):
  prepare  → lista el bucket origen del día, manifiesto JSONL + meta en destino
  worker   → CLOUD_RUN_TASK_INDEX copia 1 objeto (rewrite, sin disco)

Orquestación: Cloud Workflows (promotores_gcs_copy/workflows/daily_pipeline.yaml)
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

from config_loader import load_config
from dates import resolve_process_date
from gcs_copy import storage_client
from manifest import read_manifest_item, read_manifest_meta
from prepare import run_prepare
from worker import process_one

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


def run_worker(config: dict[str, Any]) -> int:
    dest_cfg = config["dest"]
    job_cfg = config.get("job", {})
    task_index = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
    task_count = int(os.environ.get("CLOUD_RUN_TASK_COUNT", "1"))
    process_date = resolve_process_date(config)
    manifest_prefix = job_cfg.get("manifest_prefix", "state/manifests")

    print(
        f"[worker] task_index={task_index}/{task_count} process_date={process_date}"
    )

    dest_client = storage_client(dest_cfg["project_id"])
    dest_bucket = dest_cfg["bucket_name"]
    meta = read_manifest_meta(
        dest_client,
        bucket=dest_bucket,
        process_date=process_date,
        manifest_prefix=manifest_prefix,
    )
    manifest_count = int(meta.get("count") or 0)
    if manifest_count == 0:
        print("[worker] manifiesto vacío — nada que copiar")
        print(json.dumps({"role": "worker", "status": "ok", "result": "empty_manifest"}))
        return 0
    if task_index >= manifest_count:
        print(f"[worker] task_index={task_index} >= count={manifest_count} — no-op")
        return 0

    item = read_manifest_item(
        dest_client,
        bucket=dest_bucket,
        process_date=process_date,
        manifest_prefix=manifest_prefix,
        task_index=task_index,
    )
    if item is None:
        print(f"[worker] sin ítem para index={task_index}")
        return 0

    try:
        outcome = process_one(config, item)
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
        msg = f"{item.get('key')}: {type(exc).__name__}: {exc}"
        print(f"[worker] ERROR {msg}")
        print(
            json.dumps(
                {
                    "role": "worker",
                    "status": "error",
                    "task_index": task_index,
                    "key": item.get("key"),
                    "error": msg,
                }
            )
        )
        return 1


def main() -> int:
    config = load_config(CONFIG_PATH)
    role = _resolve_role(config)
    print(f"[promotores_gcs_copy] role={role}")
    if role == "prepare":
        run_prepare(config)
        return 0
    return run_worker(config)


if __name__ == "__main__":
    sys.exit(main())
