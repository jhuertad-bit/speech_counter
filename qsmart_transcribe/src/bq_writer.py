"""Escribe resultado STT en hist raw + prd (DELETE/INSERT por gcs_uri).

Usa DML (query) en lugar de insert_rows_json para no dejar filas en el
streaming buffer — ese buffer bloquea DELETE/UPDATE posteriores (paralelismo
o reintentos del Job).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from google.cloud import bigquery
from google.api_core import exceptions as gax_exceptions


_INSERT_COLS = (
    "process_date",
    "gcs_uri",
    "file_name",
    "source_file_name",
    "audio",
    "recordid",
    "rowid",
    "codagencia",
    "gcs_path",
    "campus_code",
    "type_code",
    "correlative",
    "file_size_bytes",
    "duration_seconds",
    "sync_mode",
    "convert_method",
    "s3_uri",
    "match_status",
    "asesornombre",
    "asesorusuario",
    "asesorcodigo",
    "ndoc",
    "nombresusuario",
    "numcelular",
    "clientetipo",
    "database",
    "json_text",
    "full_response",
    "status",
    "transcripcion",
    "transcripcion_con_hablantes",
    "resumen",
    "intencion",
    "idioma",
    "tono",
    "entidades",
    "observaciones",
    "load_date",
)


def _parse_process_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value)[:10])


def _delete_by_gcs_uri(client: bigquery.Client, table: str, gcs_uri: str) -> None:
    try:
        client.query(
            f"DELETE FROM `{table}` WHERE gcs_uri = @gcs_uri",
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("gcs_uri", "STRING", gcs_uri),
                ]
            ),
        ).result()
    except gax_exceptions.BadRequest as exc:
        msg = str(exc)
        if "streaming buffer" not in msg.lower():
            raise
        # Filas de corridas previas con insert_rows_json aún en buffer.
        # Seguimos con INSERT (puede quedar duplicado hasta que limpie el buffer).
        print(
            f"[bq_writer] DELETE omitido (streaming buffer) table={table} "
            f"gcs_uri={gcs_uri}"
        )


def _insert_row_dml(client: bigquery.Client, table: str, row: dict[str, Any]) -> None:
    cols = ", ".join(_INSERT_COLS)
    params_sql = ", ".join(f"@{c}" for c in _INSERT_COLS)
    query_parameters = [
        bigquery.ScalarQueryParameter("process_date", "DATE", row["process_date"]),
        bigquery.ScalarQueryParameter("gcs_uri", "STRING", row["gcs_uri"]),
        bigquery.ScalarQueryParameter("file_name", "STRING", row["file_name"]),
        bigquery.ScalarQueryParameter("source_file_name", "STRING", row["source_file_name"]),
        bigquery.ScalarQueryParameter("audio", "STRING", row["audio"]),
        bigquery.ScalarQueryParameter("recordid", "STRING", row["recordid"]),
        bigquery.ScalarQueryParameter("rowid", "INT64", row["rowid"]),
        bigquery.ScalarQueryParameter("codagencia", "STRING", row["codagencia"]),
        bigquery.ScalarQueryParameter("gcs_path", "STRING", row["gcs_path"]),
        bigquery.ScalarQueryParameter("campus_code", "STRING", row["campus_code"]),
        bigquery.ScalarQueryParameter("type_code", "STRING", row["type_code"]),
        bigquery.ScalarQueryParameter("correlative", "STRING", row["correlative"]),
        bigquery.ScalarQueryParameter("file_size_bytes", "INT64", row["file_size_bytes"]),
        bigquery.ScalarQueryParameter("duration_seconds", "FLOAT64", row["duration_seconds"]),
        bigquery.ScalarQueryParameter("sync_mode", "STRING", row["sync_mode"]),
        bigquery.ScalarQueryParameter("convert_method", "STRING", row["convert_method"]),
        bigquery.ScalarQueryParameter("s3_uri", "STRING", row["s3_uri"]),
        bigquery.ScalarQueryParameter("match_status", "STRING", row["match_status"]),
        bigquery.ScalarQueryParameter("asesornombre", "STRING", row["asesornombre"]),
        bigquery.ScalarQueryParameter("asesorusuario", "STRING", row["asesorusuario"]),
        bigquery.ScalarQueryParameter("asesorcodigo", "STRING", row["asesorcodigo"]),
        bigquery.ScalarQueryParameter("ndoc", "STRING", row["ndoc"]),
        bigquery.ScalarQueryParameter("nombresusuario", "STRING", row["nombresusuario"]),
        bigquery.ScalarQueryParameter("numcelular", "STRING", row["numcelular"]),
        bigquery.ScalarQueryParameter("clientetipo", "STRING", row["clientetipo"]),
        bigquery.ScalarQueryParameter("database", "STRING", row["database"]),
        bigquery.ScalarQueryParameter("json_text", "STRING", row["json_text"]),
        bigquery.ScalarQueryParameter("full_response", "STRING", row["full_response"]),
        bigquery.ScalarQueryParameter("status", "STRING", row["status"]),
        bigquery.ScalarQueryParameter("transcripcion", "STRING", row["transcripcion"]),
        bigquery.ScalarQueryParameter(
            "transcripcion_con_hablantes", "STRING", row["transcripcion_con_hablantes"]
        ),
        bigquery.ScalarQueryParameter("resumen", "STRING", row["resumen"]),
        bigquery.ScalarQueryParameter("intencion", "STRING", row["intencion"]),
        bigquery.ScalarQueryParameter("idioma", "STRING", row["idioma"]),
        bigquery.ScalarQueryParameter("tono", "STRING", row["tono"]),
        bigquery.ScalarQueryParameter("entidades", "STRING", row["entidades"]),
        bigquery.ScalarQueryParameter("observaciones", "STRING", row["observaciones"]),
        bigquery.ScalarQueryParameter("load_date", "DATETIME", row["load_date"]),
    ]
    client.query(
        f"INSERT INTO `{table}` ({cols}) VALUES ({params_sql})",
        job_config=bigquery.QueryJobConfig(query_parameters=query_parameters),
    ).result()


def upsert_transcription(
    config: dict[str, Any],
    *,
    item: dict[str, Any],
    stt: dict[str, Any],
) -> None:
    gcp = config["gcp"]
    bq_cfg = config["bigquery"]
    client = bigquery.Client(project=gcp["project_id"], location=bq_cfg.get("location", "US"))

    raw_table = bq_cfg["hist_raw_table"]
    prd_table = bq_cfg["hist_prd_table"]
    gcs_uri = item["gcs_uri"]
    load_date = datetime.now(ZoneInfo("America/Lima")).replace(tzinfo=None)

    def _as_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        return int(value)

    def _as_float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        return float(value)

    row = {
        "process_date": _parse_process_date(item.get("process_date")),
        "gcs_uri": gcs_uri,
        "file_name": item.get("file_name"),
        "source_file_name": item.get("source_file_name"),
        "audio": item.get("audio"),
        "recordid": (
            None
            if item.get("recordid") is None or item.get("recordid") == ""
            else str(item.get("recordid"))
        ),
        "rowid": _as_int(item.get("rowid")),
        "codagencia": item.get("codagencia"),
        "gcs_path": item.get("gcs_path"),
        "campus_code": item.get("campus_code"),
        "type_code": item.get("type_code"),
        "correlative": item.get("correlative"),
        "file_size_bytes": _as_int(item.get("file_size_bytes")),
        "duration_seconds": _as_float(item.get("duration_seconds")),
        "sync_mode": item.get("sync_mode"),
        "convert_method": item.get("convert_method"),
        "s3_uri": item.get("s3_uri"),
        "match_status": item.get("match_status"),
        "asesornombre": item.get("asesornombre"),
        "asesorusuario": item.get("asesorusuario"),
        "asesorcodigo": item.get("asesorcodigo"),
        "ndoc": item.get("ndoc"),
        "nombresusuario": item.get("nombresusuario"),
        "numcelular": item.get("numcelular"),
        "clientetipo": item.get("clientetipo"),
        "database": item.get("database"),
        "json_text": json.dumps(stt.get("full_response") or {}, ensure_ascii=False, default=str),
        "full_response": json.dumps(stt.get("full_response") or {}, ensure_ascii=False, default=str),
        "status": stt.get("status") or "ERROR",
        "transcripcion": stt.get("transcripcion") or None,
        "transcripcion_con_hablantes": stt.get("transcripcion_con_hablantes"),
        "resumen": None,
        "intencion": None,
        "idioma": None,
        "tono": None,
        "entidades": None,
        "observaciones": None,
        "load_date": load_date,
    }

    for table in (raw_table, prd_table):
        _delete_by_gcs_uri(client, table, gcs_uri)
        _insert_row_dml(client, table, row)
