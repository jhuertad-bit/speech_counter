"""Escribe resultado STT en hist raw + prd (DELETE/INSERT por gcs_uri).

Usa DML (query) en lugar de insert_rows_json para no dejar filas en el
streaming buffer — ese buffer bloquea DELETE/UPDATE posteriores (paralelismo
o reintentos del Job).

RAW y PRD no comparten el mismo schema: se insertan columnas distintas.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from google.api_core import exceptions as gax_exceptions
from google.cloud import bigquery

# Alineado a hist_queuesmart_mp3_gen_ia_process_data_raw
_RAW_COLS: tuple[str, ...] = (
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
    "resumen",
    "intencion",
    "idioma",
    "tono",
    "entidades",
    "observaciones",
    "load_date",
)

# Alineado a hist_queuesmart_mp3_gen_ia_process_data_prd (sin gcs_path / sync / json…)
_PRD_COLS: tuple[str, ...] = (
    "process_date",
    "gcs_uri",
    "file_name",
    "source_file_name",
    "audio",
    "recordid",
    "rowid",
    "codagencia",
    "campus_code",
    "type_code",
    "correlative",
    "file_size_bytes",
    "duration_seconds",
    "match_status",
    "asesornombre",
    "asesorusuario",
    "asesorcodigo",
    "ndoc",
    "nombresusuario",
    "numcelular",
    "clientetipo",
    "database",
    "transcripcion",
    "resumen",
    "intencion",
    "idioma",
    "tono",
    "entidades",
    "observaciones",
    "load_date",
)

_PARAM_TYPES: dict[str, str] = {
    "process_date": "DATE",
    "gcs_uri": "STRING",
    "file_name": "STRING",
    "source_file_name": "STRING",
    "audio": "STRING",
    "recordid": "STRING",
    "rowid": "INT64",
    "codagencia": "STRING",
    "gcs_path": "STRING",
    "campus_code": "STRING",
    "type_code": "STRING",
    "correlative": "STRING",
    "file_size_bytes": "INT64",
    "duration_seconds": "FLOAT64",
    "sync_mode": "STRING",
    "convert_method": "STRING",
    "s3_uri": "STRING",
    "match_status": "STRING",
    "asesornombre": "STRING",
    "asesorusuario": "STRING",
    "asesorcodigo": "STRING",
    "ndoc": "STRING",
    "nombresusuario": "STRING",
    "numcelular": "STRING",
    "clientetipo": "STRING",
    "database": "STRING",
    "json_text": "STRING",
    "full_response": "STRING",
    "status": "STRING",
    "transcripcion": "STRING",
    "resumen": "STRING",
    "intencion": "STRING",
    "idioma": "STRING",
    "tono": "STRING",
    "entidades": "STRING",
    "observaciones": "STRING",
    "load_date": "DATETIME",
}


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
        print(
            f"[bq_writer] DELETE omitido (streaming buffer) table={table} "
            f"gcs_uri={gcs_uri}"
        )


def _insert_row_dml(
    client: bigquery.Client,
    table: str,
    row: dict[str, Any],
    cols: tuple[str, ...],
) -> None:
    col_sql = ", ".join(f"`{c}`" if c == "database" else c for c in cols)
    params_sql = ", ".join(f"@{c}" for c in cols)
    query_parameters = [
        bigquery.ScalarQueryParameter(c, _PARAM_TYPES[c], row.get(c)) for c in cols
    ]
    client.query(
        f"INSERT INTO `{table}` ({col_sql}) VALUES ({params_sql})",
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
        "resumen": None,
        "intencion": None,
        "idioma": None,
        "tono": None,
        "entidades": None,
        "observaciones": None,
        "load_date": load_date,
    }

    _delete_by_gcs_uri(client, raw_table, gcs_uri)
    _insert_row_dml(client, raw_table, row, _RAW_COLS)

    _delete_by_gcs_uri(client, prd_table, gcs_uri)
    _insert_row_dml(client, prd_table, row, _PRD_COLS)
