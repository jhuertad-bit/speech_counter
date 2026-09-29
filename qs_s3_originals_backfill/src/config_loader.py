"""Carga config.json con overrides por variables de entorno."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Mapping

GCP_ENV: dict[str, str] = {
    "project_id": "GCP_PROJECT_ID",
    "bucket_name": "GCP_BUCKET_NAME",
    "region": "GCP_REGION",
    "cloud_run_job_name": "GCP_JOB_NAME",
    "service_account_email": "GCP_SERVICE_ACCOUNT_EMAIL",
    "destination_prefix": "GCP_DESTINATION_PREFIX",
    "dataset_id": "GCP_DATASET_ID",
}

AWS_ENV: dict[str, str] = {
    "bucket": "AWS_S3_BUCKET",
    "prefix": "AWS_S3_PREFIX",
    "region": "AWS_REGION",
    "endpoint_url": "AWS_ENDPOINT_URL",
}

BQ_ENV: dict[str, str] = {
    "dataset_id": "GCP_DATASET_ID",
    "table_id": "GCP_BQ_TABLE_ID",
    "location": "GCP_BQ_LOCATION",
}

SYNC_ENV: dict[str, str] = {
    "start_date": "BACKFILL_START_DATE",
    "end_date": "BACKFILL_END_DATE",
    "original_subdir": "ORIGINAL_SUBDIR",
}

SECRETS_ENV: dict[str, str] = {
    "secret_resource": "GCP_AWS_SECRET_RESOURCE",
}

REQUIRED_GCP = ("project_id", "bucket_name", "region")


def _apply_section_overrides(
    section: dict[str, Any],
    env_map: Mapping[str, str],
) -> dict[str, Any]:
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
    gcp_o = _apply_section_overrides(cfg.setdefault("gcp", {}), GCP_ENV)
    aws_o = _apply_section_overrides(cfg.setdefault("aws", {}), AWS_ENV)
    bq_o = _apply_section_overrides(cfg.setdefault("bigquery", {}), BQ_ENV)
    sync_o = _apply_section_overrides(cfg.setdefault("sync", {}), SYNC_ENV)
    secrets_o = _apply_section_overrides(cfg.setdefault("secrets", {}), SECRETS_ENV)

    dataset_id = cfg.get("gcp", {}).get("dataset_id") or cfg.get("bigquery", {}).get("dataset_id")
    if dataset_id:
        cfg.setdefault("gcp", {})["dataset_id"] = dataset_id
        cfg.setdefault("bigquery", {})["dataset_id"] = dataset_id

    gcp = cfg.get("gcp", {})
    aws = cfg.get("aws", {})
    bq = cfg.get("bigquery", {})
    sync = cfg.get("sync", {})
    print("[qs_s3_originals_backfill] Config:")
    print(
        f"  GCP project={gcp.get('project_id', '')} | bucket={gcp.get('bucket_name', '')} | "
        f"prefix={gcp.get('destination_prefix', '')}"
    )
    print(f"  AWS bucket={aws.get('bucket', '')}")
    print(f"  BQ {bq.get('dataset_id', '')}.{bq.get('table_id', '')}")
    print(f"  rango {sync.get('start_date', '')} .. {sync.get('end_date', '')}")

    all_o = {**gcp_o, **aws_o, **bq_o, **sync_o, **secrets_o}
    if all_o:
        print(f"  → env overrides: {', '.join(sorted(all_o))}")
    return cfg


def validate_gcp_config(config: dict[str, Any]) -> None:
    gcp = config.get("gcp", {})
    missing = [k for k in REQUIRED_GCP if not str(gcp.get(k, "")).strip()]
    if missing:
        raise ValueError(f"Config GCP incompleta: {', '.join(missing)}")


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config = apply_env_overrides(config)
    validate_gcp_config(config)
    return config
