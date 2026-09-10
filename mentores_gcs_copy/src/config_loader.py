"""Carga config.json con overrides por variables de entorno (env > config.json)."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Mapping

SOURCE_ENV: dict[str, str] = {
    "project_id": "SOURCE_PROJECT_ID",
    "bucket_name": "SOURCE_BUCKET_NAME",
    "prefix": "SOURCE_PREFIX",
}

DEST_ENV: dict[str, str] = {
    "project_id": "DEST_PROJECT_ID",
    "bucket_name": "DEST_BUCKET_NAME",
    "destination_prefix": "DEST_PREFIX",
    "region": "GCP_REGION",
    "cloud_run_job_name": "GCP_JOB_NAME",
    "service_account_email": "GCP_SERVICE_ACCOUNT_EMAIL",
    "scheduler_name": "GCP_SCHEDULER_NAME",
}

SYNC_ENV: dict[str, str] = {
    "mode": "SYNC_MODE",
    "target_date": "SYNC_TARGET_DATE",
    "layout": "SYNC_LAYOUT",
}

REQUIRED_SOURCE = ("project_id", "bucket_name")
REQUIRED_DEST = ("project_id", "bucket_name", "region")


def _apply_section_overrides(
    section: dict[str, Any],
    env_map: Mapping[str, str],
) -> dict[str, str]:
    overrides = {
        key: os.environ[env_name].strip()
        for key, env_name in env_map.items()
        if os.environ.get(env_name, "").strip()
    }
    if overrides:
        section.update(overrides)
    return overrides


def apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    cfg = deepcopy(config)
    src_ov = _apply_section_overrides(cfg.setdefault("source", {}), SOURCE_ENV)
    dest_ov = _apply_section_overrides(cfg.setdefault("dest", {}), DEST_ENV)
    sync_ov = _apply_section_overrides(cfg.setdefault("sync", {}), SYNC_ENV)

    dest_project = os.environ.get("GCP_PROJECT_ID", "").strip()
    if dest_project:
        cfg["dest"]["project_id"] = dest_project

    dest_bucket = os.environ.get("GCP_BUCKET_NAME", "").strip()
    if dest_bucket:
        cfg["dest"]["bucket_name"] = dest_bucket

    src = cfg.get("source", {})
    dest = cfg.get("dest", {})
    print("[mentores_gcs_copy] Config:")
    print(
        f"  SRC project={src.get('project_id', '')} bucket={src.get('bucket_name', '')} "
        f"prefix={src.get('prefix', '')}"
    )
    print(
        f"  DST project={dest.get('project_id', '')} bucket={dest.get('bucket_name', '')} "
        f"prefix={dest.get('destination_prefix', '')} job={dest.get('cloud_run_job_name', '')}"
    )
    print(f"  sync mode={cfg.get('sync', {}).get('mode', '')}")
    all_ov = {**src_ov, **dest_ov, **sync_ov}
    if all_ov:
        print(f"  → env: {', '.join(sorted(all_ov))}")
    return cfg


def validate_config(config: dict[str, Any]) -> None:
    src = config.get("source", {})
    dest = config.get("dest", {})
    missing_src = [k for k in REQUIRED_SOURCE if not str(src.get(k, "")).strip()]
    missing_dst = [k for k in REQUIRED_DEST if not str(dest.get(k, "")).strip()]
    if src.get("project_id") == "REPLACE_SOURCE_PROJECT" or src.get("bucket_name") == "REPLACE_SOURCE_BUCKET":
        missing_src.append("source placeholders (SOURCE_PROJECT_ID / SOURCE_BUCKET_NAME)")
    if dest.get("bucket_name") == "REPLACE_DEST_BUCKET":
        missing_dst.append("dest placeholder (DEST_BUCKET_NAME o GCP_BUCKET_NAME)")
    if not missing_src and not missing_dst:
        return
    raise ValueError(
        "[mentores_gcs_copy] Config incompleta. "
        f"source: {missing_src or 'ok'} | dest: {missing_dst or 'ok'}"
    )


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config = apply_env_overrides(config)
    validate_config(config)
    return config
