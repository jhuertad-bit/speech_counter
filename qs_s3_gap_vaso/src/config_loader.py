"""Carga config.json con overrides por variables de entorno (env > config.json)."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Mapping, Sequence

# Mapeo campo config → variable de entorno (mismo estilo que onemarketer/gcp_runtime_log.py)
QS_S3_TO_GCS_GCP_ENV: dict[str, str] = {
    "project_id": "GCP_PROJECT_ID",
    "bucket_name": "GCP_BUCKET_NAME",
    "region": "GCP_REGION",
    "cloud_run_job_name": "GCP_JOB_NAME",
    "scheduler_name": "GCP_SCHEDULER_NAME",
    "service_account_email": "GCP_SERVICE_ACCOUNT_EMAIL",
    "destination_prefix": "GCP_DESTINATION_PREFIX",
    "dataset_id": "GCP_DATASET_ID",
}

QS_S3_TO_GCS_AWS_ENV: dict[str, str] = {
    "bucket": "AWS_S3_BUCKET",
    "prefix": "AWS_S3_PREFIX",
    "region": "AWS_REGION",
    "endpoint_url": "AWS_ENDPOINT_URL",
}

QS_S3_TO_GCS_BQ_ENV: dict[str, str] = {
    "dataset_id": "GCP_DATASET_ID",
    "table_id": "GCP_BQ_TABLE_ID",
    "location": "GCP_BQ_LOCATION",
}

QS_S3_TO_GCS_SYNC_ENV: dict[str, str] = {
    "mode": "SYNC_MODE",
    "target_date": "SYNC_TARGET_DATE",
    "lookback_days": "SYNC_LOOKBACK_DAYS",
}

QS_S3_TO_GCS_SECRETS_ENV: dict[str, str] = {
    "secret_resource": "GCP_AWS_SECRET_RESOURCE",
}

QS_S3_TO_GCS_REQUIRED_GCP: tuple[str, ...] = (
    "project_id",
    "bucket_name",
    "region",
)


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
    gcp_overrides = _apply_section_overrides(cfg.setdefault("gcp", {}), QS_S3_TO_GCS_GCP_ENV)
    aws_overrides = _apply_section_overrides(cfg.setdefault("aws", {}), QS_S3_TO_GCS_AWS_ENV)
    bq_overrides = _apply_section_overrides(cfg.setdefault("bigquery", {}), QS_S3_TO_GCS_BQ_ENV)
    sync_overrides = _apply_section_overrides(cfg.setdefault("sync", {}), QS_S3_TO_GCS_SYNC_ENV)
    secrets_overrides = _apply_section_overrides(
        cfg.setdefault("secrets", {}), QS_S3_TO_GCS_SECRETS_ENV
    )

    # Mantener dataset alineado entre gcp y bigquery cuando viene GCP_DATASET_ID
    dataset_id = cfg.get("gcp", {}).get("dataset_id") or cfg.get("bigquery", {}).get("dataset_id")
    if dataset_id:
        cfg.setdefault("gcp", {})["dataset_id"] = dataset_id
        cfg.setdefault("bigquery", {})["dataset_id"] = dataset_id

    print("[qs_s3_to_gcs] Config destino:")
    gcp = cfg.get("gcp", {})
    aws = cfg.get("aws", {})
    bq = cfg.get("bigquery", {})
    print(
        f"  GCP project={gcp.get('project_id', '')} | bucket={gcp.get('bucket_name', '')} | "
        f"region={gcp.get('region', '')} | job={gcp.get('cloud_run_job_name', '')}"
    )
    print(
        f"  AWS bucket={aws.get('bucket', '')} | prefix={aws.get('prefix', '')} | "
        f"region={aws.get('region', '')}"
    )
    print(
        f"  BQ dataset={bq.get('dataset_id', '')} | table={bq.get('table_id', '')} | "
        f"location={bq.get('location', '')}"
    )
    print(
        f"  sync mode={cfg.get('sync', {}).get('mode', '')} "
        f"lookback_days={cfg.get('sync', {}).get('lookback_days', '')}"
    )

    all_overrides = {
        **gcp_overrides,
        **aws_overrides,
        **bq_overrides,
        **sync_overrides,
        **secrets_overrides,
    }
    if all_overrides:
        print(f"  → desde env vars: {', '.join(sorted(all_overrides))}")
    else:
        print("  → desde config.json (define GCP_* / AWS_* en deploy por ambiente)")

    return cfg


def validate_gcp_config(config: dict[str, Any]) -> None:
    gcp = config.get("gcp", {})
    missing = [key for key in QS_S3_TO_GCS_REQUIRED_GCP if not str(gcp.get(key, "")).strip()]
    if not missing:
        return
    hints = [f"{QS_S3_TO_GCS_GCP_ENV.get(k, k)} → gcp.{k}" for k in missing]
    raise ValueError(
        f"[qs_s3_to_gcs] Configuración GCP incompleta. Faltan: {', '.join(missing)}. "
        f"Define en deploy: {', '.join(hints)}"
    )


def load_config(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config = apply_env_overrides(config)
    validate_gcp_config(config)
    return config
