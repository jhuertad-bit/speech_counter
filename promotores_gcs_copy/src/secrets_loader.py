"""Credenciales de la SA del proyecto origen (JSON). Nunca loguear el payload."""

from __future__ import annotations

import json
import os
from typing import Any

from google.cloud import secretmanager
from google.oauth2 import service_account

STORAGE_READONLY_SCOPE = "https://www.googleapis.com/auth/devstorage.read_only"
_UNSET = object()
_cached_sa_info: Any = _UNSET


def _read_sa_json_text(secrets_cfg: dict[str, Any]) -> str | None:
    path = (
        os.environ.get("SOURCE_SA_JSON_PATH", "").strip()
        or str(secrets_cfg.get("json_path") or "").strip()
    )
    if path:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()

    source = str(secrets_cfg.get("source") or "secret_manager").strip().lower()
    if source == "none" or source == "adc":
        return None

    resource = (
        os.environ.get("SOURCE_SA_SECRET_RESOURCE", "").strip()
        or str(secrets_cfg.get("secret_resource") or "").strip()
    )
    if not resource:
        return None
    version = str(secrets_cfg.get("version") or "latest")
    if "/versions/" not in resource:
        resource = f"{resource}/versions/{version}"

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(request={"name": resource})
    return response.payload.data.decode("utf-8")


def load_source_sa_info(secrets_cfg: dict[str, Any]) -> dict[str, Any] | None:
    global _cached_sa_info
    if _cached_sa_info is not _UNSET:
        return _cached_sa_info
    raw = _read_sa_json_text(secrets_cfg)
    if not raw:
        _cached_sa_info = None
        return None
    data = json.loads(raw)
    if not isinstance(data, dict) or "private_key" not in data or "client_email" not in data:
        raise ValueError("El JSON de origen no es una service account key válida")
    _cached_sa_info = data
    return data


def credentials_from_info(info: dict[str, Any]):
    return service_account.Credentials.from_service_account_info(
        info,
        scopes=[STORAGE_READONLY_SCOPE],
    )


def source_credentials(secrets_cfg: dict[str, Any]):
    info = load_source_sa_info(secrets_cfg)
    if info is None:
        return None
    return credentials_from_info(info)
