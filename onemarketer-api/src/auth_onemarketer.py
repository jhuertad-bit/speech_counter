"""
Autenticación OAuth OneMarketer (X-Signature).

Credenciales (sin hardcode en código):
  1) ONEMARKETER_OAUTH_USER + ONEMARKETER_OAUTH_PASSWORD  (Cloud Run --set-secrets)
  2) ONEMARKETER_API_CREDENTIALS = JSON {"user":"...","password":"..."} o {"user":"...","userpassword":"..."}
  3) ONEMARKETER_API_SECRET = id del secreto en Secret Manager (JSON, lectura local)
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime

import pytz
import requests

OAUTH_ENDPOINT = "https://utp.onemarketer.cl/utp_pregrado/oauth"


def calculate_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def calculate_login(user: str, password: str) -> str:
    return calculate_sha256(f"{user}:{password}")


def calculate_sig(user: str) -> str:
    gmt_minus_3 = pytz.timezone("America/Sao_Paulo")
    formatted_time = datetime.now(gmt_minus_3).strftime("%Y-%m-%d %H:%M")
    return calculate_sha256(f"day={formatted_time}&user={user}")


def calculate_x_signature(login: str, sig: str) -> str:
    return calculate_sha256(f"login={login}&sig={sig}")


def _parse_credentials_json(raw: str) -> tuple[str, str]:
    data = json.loads(raw)
    user = (data.get("user") or "").strip()
    password = (data.get("password") or data.get("userpassword") or "").strip()
    if not user or not password:
        raise ValueError("El JSON debe incluir 'user' y 'password' (o 'userpassword')")
    return user, password


def _read_secret_from_manager(secret_id: str) -> str:
    from google.cloud import secretmanager

    project = (
        os.environ.get("GCP_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GCLOUD_PROJECT")
    )
    if not project:
        raise ValueError("GCP_PROJECT_ID no definido para leer Secret Manager")

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_id}/versions/latest"
    return client.access_secret_version(request={"name": name}).payload.data.decode("utf-8")


def get_oauth_credentials() -> tuple[str, str]:
    """
    Orden de resolución:
      1. ONEMARKETER_OAUTH_USER + ONEMARKETER_OAUTH_PASSWORD (dos secretos separados)
      2. ONEMARKETER_API_CREDENTIALS — JSON del Secret Manager montado por Cloud Run
         (claves: user + userpassword, o user + password)
      3. ONEMARKETER_API_SECRET — id del secreto, lectura directa (local/CLI)
    """
    user = os.environ.get("ONEMARKETER_OAUTH_USER", "").strip()
    password = os.environ.get("ONEMARKETER_OAUTH_PASSWORD", "").strip()
    if user and password:
        return user, password

    # Deploy Cloud Run: --set-secrets=ONEMARKETER_API_CREDENTIALS=dev_secret_onemarketer_api:latest
    raw_json = os.environ.get("ONEMARKETER_API_CREDENTIALS", "").strip()
    if raw_json:
        return _parse_credentials_json(raw_json)

    secret_id = os.environ.get("ONEMARKETER_API_SECRET", "").strip()
    if secret_id:
        return _parse_credentials_json(_read_secret_from_manager(secret_id))

    raise ValueError(
        "Credenciales OAuth no configuradas. En Cloud Run use ONEMARKETER_API_CREDENTIALS "
        "con JSON {\"user\":\"...\",\"userpassword\":\"...\"} desde Secret Manager."
    )


def fetch_access_key(oauth_endpoint: str = OAUTH_ENDPOINT, timeout: int = 30) -> str:
    user, password = get_oauth_credentials()
    login = calculate_login(user, password)
    sig = calculate_sig(user)
    x_signature = calculate_x_signature(login, sig)

    response = requests.post(
        oauth_endpoint,
        headers={
            "X-Signature": x_signature,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"login": login, "sig": sig},
        timeout=timeout,
    )
    response.raise_for_status()

    access_key = response.json().get("access_key")
    if not access_key:
        raise ValueError("No se pudo obtener access_key del endpoint OAuth")
    return access_key


if __name__ == "__main__":
    user, _ = get_oauth_credentials()
    login = calculate_login(*get_oauth_credentials())
    sig = calculate_sig(user)
    x_signature = calculate_x_signature(login, sig)

    print(f"user: {user}")
    print(f"login: {login}")
    print(f"sig: {sig}")
    print(f"X-Signature: {x_signature}")
    print()
    print(
        f"curl --location '{OAUTH_ENDPOINT}' \\\n"
        f"--header 'X-Signature: {x_signature}' \\\n"
        f"--header 'Content-Type: application/x-www-form-urlencoded' \\\n"
        f"--data-urlencode 'login={login}' \\\n"
        f"--data-urlencode 'sig={sig}'"
    )

    access_key = fetch_access_key()
    print(f"\naccess_key OK (len={len(access_key)})")
