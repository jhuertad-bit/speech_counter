"""Carga config.json con overrides por variables de entorno (env > config.json)."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Mapping


GCP_ENV: dict[str, str] = {
    "project_id": "GCP_PROJECT_ID",
    "bucket_name": "GCP_BUCKET_NAME",
    "region": "GCP_REGION",
    "stt_location": "GCP_STT_LOCATION",
    "cloud_run_job_name": "GCP_JOB_NAME",
    "service_account_email": "GCP_SERVICE_ACCOUNT_EMAIL",
}

BQ_ENV: dict[str, str] = {
    "location": "GCP_BQ_LOCATION",
    "enriched_table": "QS_ENRICHED_TABLE",
    "hist_raw_table": "QS_HIST_RAW_TABLE",
    "hist_prd_table": "QS_HIST_PRD_TABLE",
}

JOB_ENV: dict[str, str] = {
    "manifest_prefix": "QS_MANIFEST_PREFIX",
}

STT_ENV: dict[str, str] = {
    "model": "QS_STT_MODEL",
}


def _apply_section_overrides(
    section: dict[str, Any],
    env_map: Mapping[str, str],
) -> None:
    for key, env_name in env_map.items():
        value = os.environ.get(env_name, "").strip()
        if value:
            section[key] = value


def apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    cfg = deepcopy(config)
    _apply_section_overrides(cfg.setdefault("gcp", {}), GCP_ENV)
    _apply_section_overrides(cfg.setdefault("bigquery", {}), BQ_ENV)
    _apply_section_overrides(cfg.setdefault("job", {}), JOB_ENV)
    _apply_section_overrides(cfg.setdefault("stt", {}), STT_ENV)
    return cfg


def load_config(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    return apply_env_overrides(config)


def process_date_from_env(config: dict[str, Any]) -> str:
    override = (
        os.environ.get("SYNC_PROCESS_DATE")
        or os.environ.get("SYNC_TARGET_DATE")
        or config.get("sync", {}).get("target_date")
    )
    if not override:
        raise ValueError("Falta SYNC_PROCESS_DATE (YYYY-MM-DD)")
    return str(override).strip()
