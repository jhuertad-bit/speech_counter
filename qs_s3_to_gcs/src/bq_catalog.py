"""Catálogo BigQuery de audios QueeSmart copiados S3 → GCS."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery


def load_schema(table_name: str = "hist_queesmart_mp3_catalog") -> list[dict[str, Any]]:
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


def build_catalog_row(
    *,
    parsed: dict[str, Any],
    gcs_bucket: str,
    gcs_key: str,
    s3_bucket: str,
    s3_key: str,
    file_size_bytes: int,
    sync_mode: str,
    processed_at: datetime | None = None,
    convert_method: str | None = None,
    duration_seconds: float | None = None,
    actual_format: str | None = None,
    encoding: str | None = None,
) -> dict[str, Any]:
    ts = processed_at or datetime.now(timezone.utc)
    file_date = parsed["file_date"]
    if hasattr(file_date, "isoformat"):
        fecha_audio = file_date.isoformat()
    else:
        fecha_audio = str(file_date)
    return {
        "fecha_audio": fecha_audio,
        "fecha_procesamiento": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "file_name": parsed["file_name"],
        "source_file_name": parsed.get("source_file_name") or parsed["file_name"],
        "gcs_uri": f"gs://{gcs_bucket}/{gcs_key}",
        "gcs_path": gcs_key,
        "campus_code": parsed["campus"],
        "type_code": parsed["type_code"],
        "correlative": parsed["correlative"],
        "s3_uri": f"s3://{s3_bucket}/{s3_key}",
        "s3_key": s3_key,
        "file_size_bytes": file_size_bytes,
        "duration_seconds": duration_seconds,
        "sync_mode": sync_mode,
        "convert_method": convert_method,
        "actual_format": actual_format,
        "encoding": encoding,
    }


def existing_gcs_uris(
    client: bigquery.Client,
    table_ref: str,
    gcs_uris: list[str],
    *,
    chunk_size: int = 500,
) -> set[str]:
    if not gcs_uris:
        return set()

    found: set[str] = set()
    for i in range(0, len(gcs_uris), chunk_size):
        chunk = gcs_uris[i : i + chunk_size]
        query = f"""
            SELECT gcs_uri
            FROM `{table_ref}`
            WHERE gcs_uri IN UNNEST(@uris)
        """
        rows = client.query(
            query,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("uris", "STRING", chunk),
                ]
            ),
        ).result()
        found.update(row.gcs_uri for row in rows if row.gcs_uri)
    return found


def insert_catalog_rows(
    client: bigquery.Client,
    table_ref: str,
    rows: list[dict[str, Any]],
    *,
    batch_size: int = 500,
) -> int:
    if not rows:
        return 0

    uris = [row["gcs_uri"] for row in rows]
    already = existing_gcs_uris(client, table_ref, uris)
    pending = [row for row in rows if row["gcs_uri"] not in already]
    if not pending:
        return 0

    parts = table_ref.split(".")
    if len(parts) != 3:
        raise ValueError(f"table_ref inválido: {table_ref}")
    project_id, dataset_id, table_name = parts
    table = client.dataset(dataset_id, project=project_id).table(table_name)
    inserted = 0
    for i in range(0, len(pending), batch_size):
        chunk = pending[i : i + batch_size]
        errors = client.insert_rows_json(table, chunk)
        if errors:
            raise RuntimeError(f"Errores insertando en BigQuery: {errors[:3]}")
        inserted += len(chunk)
    return inserted


def catalog_files(
    *,
    project_id: str,
    dataset_id: str,
    table_id: str,
    rows: list[dict[str, Any]],
    location: str = "US",
) -> int:
    if not rows:
        return 0

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        deduped[row["gcs_uri"]] = row
    unique_rows = list(deduped.values())

    client = bigquery.Client(project=project_id)
    schema = load_schema("hist_queesmart_mp3_catalog")
    table_ref = ensure_table(
        client,
        project_id,
        dataset_id,
        table_id,
        schema,
        location=location,
    )
    return insert_catalog_rows(client, table_ref, unique_rows)
