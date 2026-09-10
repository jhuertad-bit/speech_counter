"""Catálogo BigQuery de audios Cita Mentor (GCS origen → GCS destino)."""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from typing import Any

from google.cloud import bigquery

_TABLE_SCHEMA = "hist_cita_mentor_audio_catalog"
_DATE_FOLDER_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")


def load_schema(table_name: str = _TABLE_SCHEMA) -> list[dict[str, Any]]:
    schema_path = os.path.join(os.path.dirname(__file__), "tablas", f"{table_name}.json")
    with open(schema_path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def schema_fields(schema: list[dict[str, Any]]) -> list[bigquery.SchemaField]:
    return [
        bigquery.SchemaField(field["name"], field["type"], mode=field["mode"])
        for field in schema
    ]


def ensure_table(
    client: bigquery.Client,
    project_id: str,
    dataset_id: str,
    table_id: str,
    schema: list[dict[str, Any]],
    *,
    partition_field: str = "fecha_audio",
    location: str = "US",
) -> str:
    table_ref = f"{project_id}.{dataset_id}.{table_id}"
    try:
        client.get_table(table_ref)
        return table_ref
    except Exception:
        pass

    dataset_ref = f"{project_id}.{dataset_id}"
    try:
        client.get_dataset(dataset_ref)
    except Exception:
        dataset = bigquery.Dataset(dataset_ref)
        dataset.location = location
        client.create_dataset(dataset, timeout=30)

    table = bigquery.Table(table_ref, schema=schema_fields(schema))
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field=partition_field,
    )
    client.create_table(table)
    return table_ref


def parse_path_parts(gcs_path: str) -> dict[str, Any]:
    """
    audios/mentores/DD-MM-YYYY/{folder_id}/{file}.m4a
    audios/DD-MM-YYYY/{folder_uuid}/{file}.m4a
    o DD-MM-YYYY/{folder_id}/{file}.m4a
    """
    parts = [p for p in (gcs_path or "").strip("/").split("/") if p]
    if parts and parts[0].lower() == "audios":
        parts = parts[1:]
    # Canal mentores (u otro segmento no-fecha) antes de la carpeta DD-MM-YYYY.
    while parts and not _DATE_FOLDER_RE.match(parts[0]):
        parts = parts[1:]
    fecha_audio: date | None = None
    folder_uuid: str | None = None
    file_name = parts[-1] if parts else ""
    if parts:
        m = _DATE_FOLDER_RE.match(parts[0])
        if m:
            day, month, year = m.groups()
            fecha_audio = date(int(year), int(month), int(day))
        if len(parts) >= 3:
            folder_uuid = parts[1]
        elif len(parts) == 2:
            folder_uuid = None
    return {
        "fecha_audio": fecha_audio,
        "folder_uuid": folder_uuid,
        "file_name": file_name,
    }


def build_catalog_row(
    *,
    process_date: str,
    dest_bucket: str,
    dest_key: str,
    source_bucket: str,
    source_key: str,
    file_size_bytes: int | None,
    sync_mode: str,
    copy_result: str,
    content_type: str | None = None,
    duration_seconds: float | None = None,
    audio_codec: str | None = None,
    sample_rate_hz: int | None = None,
    channels: int | None = None,
    format_name: str | None = None,
    bit_rate: int | None = None,
    processed_at: datetime | None = None,
) -> dict[str, Any]:
    ts = processed_at or datetime.now(timezone.utc)
    parsed = parse_path_parts(dest_key)
    fecha = parsed["fecha_audio"]
    if fecha is None:
        fecha = date.fromisoformat(process_date)
    return {
        "fecha_audio": fecha.isoformat(),
        "fecha_procesamiento": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file_name": parsed["file_name"] or dest_key.rsplit("/", 1)[-1],
        "gcs_uri": f"gs://{dest_bucket}/{dest_key}",
        "gcs_path": dest_key,
        "source_gcs_uri": f"gs://{source_bucket}/{source_key}",
        "source_gcs_path": source_key,
        "folder_uuid": parsed.get("folder_uuid"),
        "file_size_bytes": file_size_bytes,
        "content_type": content_type or "audio/mp4",
        "duration_seconds": duration_seconds,
        "audio_codec": audio_codec,
        "sample_rate_hz": sample_rate_hz,
        "channels": channels,
        "format_name": format_name,
        "bit_rate": bit_rate,
        "sync_mode": sync_mode,
        "copy_result": copy_result,
    }


def gcs_uri_exists(client: bigquery.Client, table_ref: str, gcs_uri: str) -> bool:
    query = f"""
        SELECT 1
        FROM `{table_ref}`
        WHERE gcs_uri = @uri
        LIMIT 1
    """
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("uri", "STRING", gcs_uri)]
        ),
    )
    return any(True for _ in job.result())


def insert_catalog_row(client: bigquery.Client, table_ref: str, row: dict[str, Any]) -> None:
    errors = client.insert_rows_json(table_ref, [row])
    if errors:
        raise RuntimeError(f"BigQuery insert_rows_json errors: {errors}")


def catalog_one(
    config: dict[str, Any],
    *,
    process_date: str,
    dest_key: str,
    source_key: str,
    file_size_bytes: int | None,
    copy_result: str,
    content_type: str | None = None,
    duration_seconds: float | None = None,
    audio_codec: str | None = None,
    sample_rate_hz: int | None = None,
    channels: int | None = None,
    format_name: str | None = None,
    bit_rate: int | None = None,
) -> dict[str, Any]:
    bq_cfg = config.get("bigquery", {})
    if not bool(bq_cfg.get("enabled", True)):
        return {"catalog": "skipped_disabled"}

    project_id = str(bq_cfg.get("project_id") or config["dest"]["project_id"])
    dataset_id = str(bq_cfg.get("dataset_id") or "raw_cita_promotor")
    table_id = str(bq_cfg.get("table_id") or _TABLE_SCHEMA)
    location = str(bq_cfg.get("location") or "US")

    client = bigquery.Client(project=project_id, location=location)
    schema = load_schema(table_id)
    table_ref = ensure_table(client, project_id, dataset_id, table_id, schema, location=location)

    dest_bucket = config["dest"]["bucket_name"]
    source_bucket = config["source"]["bucket_name"]
    gcs_uri = f"gs://{dest_bucket}/{dest_key}"

    if gcs_uri_exists(client, table_ref, gcs_uri):
        return {"catalog": "already_in_bq", "gcs_uri": gcs_uri, "table": table_ref}

    row = build_catalog_row(
        process_date=process_date,
        dest_bucket=dest_bucket,
        dest_key=dest_key,
        source_bucket=source_bucket,
        source_key=source_key,
        file_size_bytes=file_size_bytes,
        sync_mode=str(config.get("sync", {}).get("mode") or "daily_yesterday"),
        copy_result=copy_result,
        content_type=content_type,
        duration_seconds=duration_seconds,
        audio_codec=audio_codec,
        sample_rate_hz=sample_rate_hz,
        channels=channels,
        format_name=format_name,
        bit_rate=bit_rate,
    )
    insert_catalog_row(client, table_ref, row)
    return {
        "catalog": "inserted",
        "gcs_uri": gcs_uri,
        "table": table_ref,
        "duration_seconds": duration_seconds,
    }
