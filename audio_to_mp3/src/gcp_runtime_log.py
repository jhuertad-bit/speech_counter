#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Logs de identidad GCP y resolución de config por ambiente (env > config.json)."""

from __future__ import annotations

import os
from typing import Any, Dict, Mapping, Optional, Sequence

# --- Presets por servicio -----------------------------------------------------

ONEMARKETER_ETL_ENV: Dict[str, str] = {
    "project_id": "GCP_PROJECT_ID",
    "bucket_name": "GCP_BUCKET_NAME",
    "dataset_id": "GCP_DATASET_ID",
    "region": "GCP_REGION",
    "function_name": "GCP_FUNCTION_NAME",
    "scheduler_name": "GCP_SCHEDULER_NAME",
    "service_account_name": "GCP_SERVICE_ACCOUNT_NAME",
}
ONEMARKETER_ETL_REQUIRED = ("project_id", "bucket_name", "dataset_id", "region")

ONEMARKETER_API_ENV: Dict[str, str] = {
    "project_id": "GCP_PROJECT_ID",
    "bucket_name": "GCP_BUCKET_NAME",
    "dataset_id": "GCP_DATASET_ID",
    "region": "GCP_REGION",
    "service_name": "GCP_SERVICE_NAME",
    "service_account_name": "GCP_SERVICE_ACCOUNT_NAME",
}
ONEMARKETER_API_REQUIRED = ("project_id", "bucket_name", "dataset_id")

AUDIO_MP3_ENV: Dict[str, str] = {
    "project_id": "GCP_PROJECT_ID",
    "bucket_name": "GCP_BUCKET_NAME",
    "region": "GCP_REGION",
    "path_audios_input": "GCP_PATH_AUDIOS_INPUT",
    "path_audios_mp3": "GCP_PATH_AUDIOS_MP3",
    "cloud_function_name": "GCP_FUNCTION_NAME",
    "service_account_email": "GCP_SERVICE_ACCOUNT_EMAIL",
}
AUDIO_MP3_REQUIRED = ("project_id", "bucket_name", "path_audios_input", "path_audios_mp3")


def _email_from_metadata_server() -> str | None:
    """SA real en Cloud Run/Functions (más fiable que ADC cuando devuelve 'default')."""
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://metadata.google.internal/computeMetadata/v1/"
            "instance/service-accounts/default/email",
            headers={"Metadata-Flavor": "Google"},
        )
        with urllib.request.urlopen(req, timeout=2) as resp:
            email = resp.read().decode("utf-8").strip()
            return email if "@" in email else None
    except Exception:
        return None


def get_runtime_service_account_email() -> str:
    meta = _email_from_metadata_server()
    if meta:
        return meta

    try:
        import google.auth

        credentials, _ = google.auth.default()
        email = getattr(credentials, "service_account_email", None)
        if email and "@" in str(email) and str(email) != "default":
            return str(email)
        return (
            f"SIN_RESOLVER ({type(credentials).__name__}) — "
            "falta --service-account en deploy; revisa _SERVICE_ACCOUNT en Cloud Build"
        )
    except Exception as exc:
        return f"ERROR al resolver: {exc}"


def apply_gcp_env_overrides(
    config: Dict[str, Any],
    env_map: Mapping[str, str],
    *,
    service_label: str = "",
) -> Dict[str, Any]:
    gcp = config.setdefault("gcp", {})
    overrides = {
        key: os.environ[env_name].strip()
        for key, env_name in env_map.items()
        if os.environ.get(env_name, "").strip()
    }
    if overrides:
        gcp.update(overrides)

    label = f"[{service_label}] " if service_label else ""
    print(
        f"{label}GCP destino: "
        f"project={gcp.get('project_id', '')} | "
        f"bucket={gcp.get('bucket_name', '')} | "
        f"dataset={gcp.get('dataset_id', '')} | "
        f"region={gcp.get('region', '')}"
    )
    if overrides:
        print(f"{label}  → desde env vars: {', '.join(sorted(overrides))}")
    else:
        print(f"{label}  → desde config.json (define GCP_* en deploy por ambiente)")
    return config


def validate_gcp_config(
    config: Dict[str, Any],
    required: Sequence[str],
    env_map: Mapping[str, str],
    *,
    service_label: str = "",
) -> None:
    gcp = config.get("gcp", {})
    missing = [key for key in required if not str(gcp.get(key, "")).strip()]
    if not missing:
        return

    hints = [f"{env_map.get(k, k)} → gcp.{k}" for k in missing]
    label = f"[{service_label}] " if service_label else ""
    raise ValueError(
        f"{label}Configuración GCP incompleta. Faltan: {', '.join(missing)}. "
        f"Define en deploy: {', '.join(hints)}"
    )


def print_runtime_gcp_info(
    config: Dict[str, Any],
    *,
    service_label: str = "",
    extra_lines: Optional[Sequence[str]] = None,
    config_sa_field: str = "service_account_name",
) -> None:
    gcp = config.get("gcp", {})
    sa_email = get_runtime_service_account_email()

    config_sa_ref = (gcp.get(config_sa_field) or "").strip()
    if config_sa_field == "service_account_email" and config_sa_ref:
        config_sa_display = config_sa_ref
    elif config_sa_ref and gcp.get("project_id"):
        config_sa_display = f"{config_sa_ref}@{gcp.get('project_id')}.iam.gserviceaccount.com"
    else:
        config_sa_display = f"(no definida en env/config — campo {config_sa_field})"

    header = f"IDENTIDAD GCP [{service_label}]" if service_label else "IDENTIDAD GCP"
    print("=" * 60)
    print(header)
    print("  Service Account RUNTIME (pedir permisos IAM aquí):")
    print(f"    {sa_email}")
    print(f"  Service Account en config/env ({config_sa_field}, referencia):")
    print(f"    {config_sa_display}")
    if "@" not in sa_email or sa_email == "default":
        print(
            "  ⚠️  RUNTIME NO CONFIGURADA: el deploy no tiene --service-account. "
            "Usa la SA default del proyecto (Compute). Revisa _SERVICE_ACCOUNT en Cloud Build."
        )
    elif (
        config_sa_ref
        and "@" in sa_email
        and config_sa_display != sa_email
        and not config_sa_display.startswith("(")
    ):
        print(
            "  ⚠️  NO COINCIDEN: IAM va a la RUNTIME, no al nombre en config/env. "
            "Revisa _SERVICE_ACCOUNT en Cloud Build."
        )
    print(f"  Proyecto:   {gcp.get('project_id', '')}")
    print(f"  Dataset BQ: {gcp.get('dataset_id', '')}")
    print(f"  Bucket GCS: {gcp.get('bucket_name', '')}")
    print(f"  Región:     {gcp.get('region', '')}")
    if extra_lines:
        for line in extra_lines:
            print(f"  {line}")
    print("=" * 60)


def finalize_gcp_config(
    config: Dict[str, Any],
    env_map: Mapping[str, str],
    required: Sequence[str],
    *,
    service_label: str = "",
) -> Dict[str, Any]:
    config = apply_gcp_env_overrides(config, env_map, service_label=service_label)
    validate_gcp_config(config, required, env_map, service_label=service_label)
    return config
