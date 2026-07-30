"""Escribe resultado STT en hist raw + prd (DELETE/INSERT por gcs_uri)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from google.cloud import bigquery


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

    row = {
        "process_date": item.get("process_date"),
        "gcs_uri": gcs_uri,
        "file_name": item.get("file_name"),
        "source_file_name": item.get("source_file_name"),
        "audio": item.get("audio"),
        "recordid": item.get("recordid"),
        "rowid": item.get("rowid"),
        "codagencia": item.get("codagencia"),
        "gcs_path": item.get("gcs_path"),
        "campus_code": item.get("campus_code"),
        "type_code": item.get("type_code"),
        "correlative": item.get("correlative"),
        "file_size_bytes": item.get("file_size_bytes"),
        "duration_seconds": item.get("duration_seconds"),
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
        "load_date": load_date.isoformat(sep=" "),
    }

    # DELETE + INSERT en raw y prd (idempotente por gcs_uri)
    for table in (raw_table, prd_table):
        client.query(
            f"DELETE FROM `{table}` WHERE gcs_uri = @gcs_uri",
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("gcs_uri", "STRING", gcs_uri),
                ]
            ),
        ).result()

        errors = client.insert_rows_json(table, [row])
        if errors:
            raise RuntimeError(f"insert_rows_json falló en {table}: {errors}")
