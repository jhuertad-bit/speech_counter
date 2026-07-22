#!/usr/bin/env python3
"""
Cloud Run Job — QueeSmart S3 → GCS (prepare | worker).

Roles (env QS_JOB_ROLE o config job.role):
  prepare  → lista S3 del día, escribe manifiesto JSONL + meta en GCS, exit 0
  worker   → CLOUD_RUN_TASK_INDEX toma 1 línea del manifiesto, procesa y cataloga

La orquestación de SPs (consolidate / STT / Gemini) vive en Cloud Workflows;
este Job ya NO encadena stored procedures.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from google.cloud import storage

from audio_paths import DEFAULT_FILENAME_REGEX, resolve_sync_mode
from config_loader import load_config
from manifest import read_manifest_item, read_manifest_meta
from sync import (
    build_s3_client,
    parse_manifest_parsed,
    read_state,
    run_prepare,
    write_state,
)
from worker import is_unconvertible_error, process_one_candidate

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


def _process_date(config: dict[str, Any]) -> str:
    override = (
        os.environ.get("SYNC_PROCESS_DATE")
        or os.environ.get("SYNC_TARGET_DATE")
        or config.get("sync", {}).get("target_date")
    )
    if override:
        return str(override).strip()
    # Fallback: meta del último prepare en state
    gcp = config["gcp"]
    gcs = storage.Client(project=gcp.get("project_id"))
    state = read_state(gcs, gcp["bucket_name"], gcp.get("state_object", "state/s3_to_gcs_last_sync.json"))
    if state.get("last_prepare_process_date"):
        return str(state["last_prepare_process_date"])
    tz_name = config.get("sync", {}).get("timezone", "America/Lima")
    return (datetime.now(ZoneInfo(tz_name)).date()).isoformat()


def run_worker(config: dict[str, Any]) -> int:
    gcp_cfg = config["gcp"]
    aws_cfg = config["aws"]
    sync_cfg = config.get("sync", {})
    job_cfg = config.get("job", {})
    secrets_cfg = config.get("secrets", {})
    treat_unconvertible = bool(sync_cfg.get("treat_unconvertible_as_skip", True))

    task_index = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
    task_count = int(os.environ.get("CLOUD_RUN_TASK_COUNT", "1"))
    process_date = _process_date(config)
    manifest_prefix = job_cfg.get("manifest_prefix", "state/manifests")
    sync_mode = resolve_sync_mode(sync_cfg)
    filename_regex = sync_cfg.get("filename_regex", DEFAULT_FILENAME_REGEX)

    print(
        f"[worker] task_index={task_index}/{task_count} "
        f"process_date={process_date} mode={sync_mode}"
    )

    gcs_client = storage.Client(project=gcp_cfg.get("project_id"))
    gcs_bucket = gcp_cfg["bucket_name"]
    state_object = gcp_cfg.get("state_object", "state/s3_to_gcs_last_sync.json")

    meta = read_manifest_meta(
        gcs_client,
        bucket=gcs_bucket,
        process_date=process_date,
        manifest_prefix=manifest_prefix,
    )
    manifest_count = int(meta.get("count") or 0)
    if manifest_count == 0:
        print("[worker] manifiesto vacío — nada que procesar")
        summary = {
            "role": "worker",
            "status": "ok",
            "task_index": task_index,
            "manifest_count": 0,
            "result": "empty_manifest",
        }
        print(json.dumps(summary, indent=2))
        return 0

    if task_index >= manifest_count:
        # Tasks sobrantes (si se lanzó con tasks > count): éxito no-op
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
        print(f"[worker] sin ítem para index={task_index}")
        return 0

    # Poison list
    prior = read_state(gcs_client, gcs_bucket, state_object)
    unconvertible: set[str] = {
        str(k) for k in (prior.get("unconvertible_s3_keys") or []) if k
    }
    s3_key = item["key"]
    if s3_key in unconvertible:
        print(f"[worker] SKIP corrupt (state) {s3_key}")
        summary = {
            "role": "worker",
            "status": "ok",
            "task_index": task_index,
            "result": "skipped_corrupt_state",
            "s3_key": s3_key,
        }
        print(json.dumps(summary, indent=2))
        return 0

    item["parsed"] = parse_manifest_parsed(item, filename_regex)
    s3_client = build_s3_client(aws_cfg, secrets_cfg)

    try:
        outcome = process_one_candidate(
            config=config,
            s3_client=s3_client,
            gcs_client=gcs_client,
            item=item,
            sync_mode=sync_mode,
        )
        summary = {
            "role": "worker",
            "status": "ok" if outcome.get("status") != "error" else "error",
            "task_index": task_index,
            "manifest_count": manifest_count,
            **outcome,
        }
        print(json.dumps(summary, indent=2, default=str))
        return 0 if outcome.get("status") != "error" else 1
    except Exception as exc:  # noqa: BLE001
        msg = f"{s3_key}: {type(exc).__name__}: {exc}"
        if treat_unconvertible and is_unconvertible_error(exc):
            unconvertible.add(s3_key)
            new_state = dict(prior)
            new_state["unconvertible_s3_keys"] = sorted(unconvertible)[-5000:]
            write_state(gcs_client, gcs_bucket, state_object, new_state)
            print(f"[worker] SKIP corrupt {msg}")
            summary = {
                "role": "worker",
                "status": "ok",
                "task_index": task_index,
                "result": "skipped_corrupt",
                "s3_key": s3_key,
                "error": msg,
            }
            print(json.dumps(summary, indent=2))
            return 0
        print(f"[worker] ERROR {msg}")
        summary = {
            "role": "worker",
            "status": "error",
            "task_index": task_index,
            "s3_key": s3_key,
            "error": msg,
        }
        print(json.dumps(summary, indent=2))
        return 1


def main() -> int:
    config = load_config(CONFIG_PATH)
    role = _resolve_role(config)
    print(f"[qs_s3_to_gcs] role={role}")

    if role == "prepare":
        run_prepare(config)
        return 0

    return run_worker(config)


if __name__ == "__main__":
    sys.exit(main())
