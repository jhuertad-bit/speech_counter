"""Conexión y consultas a SQL Server (on-prem, no Azure)."""

from __future__ import annotations

import os
import re
from typing import Any

import pymssql

AUDIO_DATE_RE = re.compile(r"-(?P<date>\d{8})-")


def load_sql_credentials(secrets_cfg: dict[str, Any]) -> tuple[str, str]:
    user_env = secrets_cfg.get("sql_user_env", "SQL_SERVER_USER")
    pass_env = secrets_cfg.get("sql_password_env", "SQL_SERVER_PASSWORD")
    user = os.environ.get(user_env, "").strip()
    password = os.environ.get(pass_env, "").strip()
    if not user or not password:
        raise ValueError(f"Faltan {user_env} y/o {pass_env}")
    return user, password


def connect_sql(sql_cfg: dict[str, Any], secrets_cfg: dict[str, Any]):
    user, password = load_sql_credentials(secrets_cfg)
    return pymssql.connect(
        server=sql_cfg["host"],
        user=user,
        password=password,
        database=sql_cfg["database"],
        port=int(sql_cfg.get("port", 1433)),
        login_timeout=int(sql_cfg.get("login_timeout_seconds", 30)),
        tds_version="7.4",
    )


def _qualified_table(sql_cfg: dict[str, Any]) -> str:
    schema = (sql_cfg.get("schema") or "dbo").strip()
    table = sql_cfg["table"].strip()
    return f"[{schema}].[{table}]"


def build_select_sql(sql_cfg: dict[str, Any], columns: list[str]) -> str:
    custom = sql_cfg.get("query")
    if custom:
        return str(custom).strip()
    quoted = ", ".join(f"[{col}]" for col in columns)
    return f"SELECT {quoted} FROM {_qualified_table(sql_cfg)}"


def fetch_rows(
    sql_cfg: dict[str, Any],
    secrets_cfg: dict[str, Any],
    columns: list[str],
) -> list[dict[str, Any]]:
    query = build_select_sql(sql_cfg, columns)
    print(f"[sql] query={query[:200]}{'...' if len(query) > 200 else ''}")
    conn = connect_sql(sql_cfg, secrets_cfg)
    try:
        with conn.cursor(as_dict=True) as cursor:
            cursor.execute(query)
            return list(cursor.fetchall())
    finally:
        conn.close()


def parse_audio_date(audio: str | None) -> str | None:
    if not audio:
        return None
    match = AUDIO_DATE_RE.search(audio)
    if not match:
        return None
    raw = match.group("date")
    return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
