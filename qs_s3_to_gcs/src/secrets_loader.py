"""Carga credenciales AWS desde env vars o Secret Manager (JSON)."""

from __future__ import annotations

import json
import os
from typing import Any

from google.cloud import secretmanager


def _parse_secret_json(payload: str, secrets_cfg: dict[str, Any]) -> tuple[str, str]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("El secret debe ser un objeto JSON con las claves AWS")

    id_field = secrets_cfg.get("aws_access_key_id_field", "aws_access_key_id")
    secret_field = secrets_cfg.get("aws_secret_access_key_field", "aws_secret_access_key")

    access_key = data.get(id_field)
    secret_key = data.get(secret_field)
    if not access_key or not secret_key:
        raise ValueError(
            f"Faltan '{id_field}' o '{secret_field}' en el JSON de Secret Manager"
        )
    return str(access_key), str(secret_key)


def load_aws_credentials(secrets_cfg: dict[str, Any]) -> tuple[str | None, str | None]:
    """
    Orden de resolución:
      1) Variables de entorno (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
      2) Secret Manager (JSON en QueeSmartSecrets u otro secret configurado)
    """
    id_env = secrets_cfg.get("aws_access_key_id_env", "AWS_ACCESS_KEY_ID")
    secret_env = secrets_cfg.get("aws_secret_access_key_env", "AWS_SECRET_ACCESS_KEY")

    access_key = os.environ.get(id_env)
    secret_key = os.environ.get(secret_env)
    if access_key and secret_key:
        return access_key, secret_key

    if secrets_cfg.get("source") != "secret_manager":
        return access_key, secret_key

    resource = secrets_cfg.get("secret_resource", "").strip()
    if not resource:
        project = secrets_cfg.get("project_id") or os.environ.get(
            "GCP_PROJECT_ID", os.environ.get("GCP_PROJECT", "")
        )
        secret_id = secrets_cfg.get("secret_id", "QueeSmartSecrets")
        if not project:
            raise ValueError("secrets.project_id o GCP_PROJECT requerido para Secret Manager")
        resource = f"projects/{project}/secrets/{secret_id}"

    version = secrets_cfg.get("version", "latest")
    if "/versions/" not in resource:
        resource = f"{resource}/versions/{version}"

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": resource})
    payload = response.payload.data.decode("utf-8")
    return _parse_secret_json(payload, secrets_cfg)
