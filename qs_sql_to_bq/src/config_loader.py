"""Carga config.json con overrides por variables de entorno (env > config.json)."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any, Mapping

SQL_TO_BQ_GCP_ENV: dict[str, str] = {
    "project_id": "GCP_PROJECT_ID",
    "region": "GCP_REGION",
    "dataset_id": "GCP_DATASET_ID",
    "cloud_run_job_name": "GCP_JOB_NAME",
    "scheduler_name": "GCP_SCHEDULER_NAME",
    "service_account_email": "GCP_SERVICE_ACCOUNT_EMAIL",
}

SQL_TO_BQ_SQL_ENV: dict[str, str] = {
    "host": "SQL_SERVER_HOST",
    "port": "SQL_SERVER_PORT",
    "database": "SQL_SERVER_DATABASE",
    "schema": "SQL_SERVER_SCHEMA",
    "table": "SQL_SOURCE_TABLE",
    "query": "SQL_CUSTOM_QUERY",
}

SQL_TO_BQ_BQ_ENV: dict[str, str] = {
    "dataset_id": "GCP_DATASET_ID",
    "table_id": "GCP_BQ_TABLE_ID",
    "location": "GCP_BQ_LOCATION",
}

SQL_TO_BQ_SYNC_ENV: dict[str, str] = {
    "mode": "SYNC_MODE",
    "target_date": "SYNC_TARGET_DATE",
    "lookback_days": "SYNC_LOOKBACK_DAYS",
}

SQL_TO_BQ_REQUIRED_GCP: tuple[str, ...] = ("project_id", "region")
SQL_TO_BQ_REQUIRED_SQL_AT_RUNTIME: tuple[str, ...] = (
    "host",
    "database",
    "table",
)


def _apply_section_overrides(section: dict[str, Any], env_map: Mapping[str, str]) -> dict[str, Any]:
    overrides = {
        key: os.environ[env_name].strip()
        for key, env_name in env_map.items()
        if os.environ.get(env_name, "").strip()
    }
    if overrides:
        section.update(overrides)
    if "port" in section and section.get("port") is not None:
        section["port"] = int(section["port"])
    return overrides


def apply_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    cfg = deepcopy(config)
    gcp_overrides = _apply_section_overrides(cfg.setdefault("gcp", {}), SQL_TO_BQ_GCP_ENV)
    sql_overrides = _apply_section_overrides(cfg.setdefault("sql", {}), SQL_TO_BQ_SQL_ENV)
    bq_overrides = _apply_section_overrides(cfg.setdefault("bigquery", {}), SQL_TO_BQ_BQ_ENV)
    sync_overrides = _apply_section_overrides(cfg.setdefault("sync", {}), SQL_TO_BQ_SYNC_ENV)
    if cfg.get("sync", {}).get("lookback_days") is not None:
        cfg["sync"]["lookback_days"] = int(cfg["sync"]["lookback_days"])

    dataset_id = cfg.get("gcp", {}).get("dataset_id") or cfg.get("bigquery", {}).get("dataset_id")
    if dataset_id:
        cfg.setdefault("gcp", {})["dataset_id"] = dataset_id
        cfg.setdefault("bigquery", {})["dataset_id"] = dataset_id

    print("[qs_sql_to_bq] Config:")
    gcp = cfg.get("gcp", {})
    sql = cfg.get("sql", {})
    bq = cfg.get("bigquery", {})
    print(
        f"  GCP project={gcp.get('project_id', '')} | dataset={gcp.get('dataset_id', '')} | "
        f"job={gcp.get('cloud_run_job_name', '')}"
    )
    print(
        f"  SQL host={sql.get('host', '') or '(pendiente)'} | db={sql.get('database', '') or '(pendiente)'} | "
        f"table={sql.get('schema', 'dbo')}.{sql.get('table', '') or '(pendiente)'}"
    )
    print(
        f"  BQ table={bq.get('dataset_id', '')}.{bq.get('table_id', '')} | "
        f"sync={cfg.get('sync', {}).get('mode', '')}"
    )
    all_overrides = {**gcp_overrides, **sql_overrides, **bq_overrides, **sync_overrides}
    if all_overrides:
        print(f"  → desde env vars: {', '.join(sorted(all_overrides))}")

    return cfg


def validate_config(config: dict[str, Any], *, strict_sql: bool = True) -> None:
    gcp = config.get("gcp", {})
    missing_gcp = [k for k in SQL_TO_BQ_REQUIRED_GCP if not str(gcp.get(k, "")).strip()]
    if missing_gcp:
        raise ValueError(f"GCP incompleto: {missing_gcp}")

    if not strict_sql:
        return

    sql = config.get("sql", {})
    if sql.get("query"):
        return
    missing_sql = [k for k in SQL_TO_BQ_REQUIRED_SQL_AT_RUNTIME if not str(sql.get(k, "")).strip()]
    if missing_sql:
        raise ValueError(
            f"SQL incompleto: {missing_sql}. Define SQL_SERVER_* y SQL_SOURCE_TABLE en el activador "
            "o completa config.json / SQL_CUSTOM_QUERY."
        )

    secrets = config.get("secrets", {})
    user_env = secrets.get("sql_user_env", "SQL_SERVER_USER")
    pass_env = secrets.get("sql_password_env", "SQL_SERVER_PASSWORD")
    if not os.environ.get(user_env) or not os.environ.get(pass_env):
        raise ValueError(
            f"Credenciales SQL faltantes: {user_env} y {pass_env} (variables de entorno del Job)."
        )


def load_config(path: str, *, strict_sql: bool = True) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        config = json.load(handle)
    config = apply_env_overrides(config)
    validate_config(config, strict_sql=strict_sql)
    return config
