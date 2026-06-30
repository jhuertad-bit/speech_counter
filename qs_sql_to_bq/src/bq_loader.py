"""Carga filas en BigQuery (raw_queuesmart)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery


def load_schema(table_name: str = "hist_queuesmart_ticketero_raw") -> list[dict[str, Any]]:
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
    partition_field: str = "fecha_extraccion",
    location: str = "us-central1",
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


def existing_record_ids(
    client: bigquery.Client,
    table_ref: str,
    record_ids: list[str],
    *,
    fecha_extraccion: str | None = None,
    chunk_size: int = 500,
) -> set[str]:
    if not record_ids:
        return set()

    found: set[str] = set()
    for i in range(0, len(record_ids), chunk_size):
        chunk = [rid for rid in record_ids[i : i + chunk_size] if rid]
        if not chunk:
            continue
        where_date = "AND fecha_extraccion = @fecha_extraccion" if fecha_extraccion else ""
        query = f"""
            SELECT record_id
            FROM `{table_ref}`
            WHERE record_id IN UNNEST(@ids)
            {where_date}
        """
        params = [bigquery.ArrayQueryParameter("ids", "STRING", chunk)]
        if fecha_extraccion:
            params.append(
                bigquery.ScalarQueryParameter("fecha_extraccion", "DATE", fecha_extraccion)
            )
        rows = client.query(
            query,
            job_config=bigquery.QueryJobConfig(query_parameters=params),
        ).result()
        found.update(row.record_id for row in rows if row.record_id)
    return found


def insert_rows(
    client: bigquery.Client,
    table_ref: str,
    rows: list[dict[str, Any]],
    *,
    batch_size: int = 500,
) -> int:
    if not rows:
        return 0

    parts = table_ref.split(".")
    if len(parts) != 3:
        raise ValueError(f"table_ref inválido: {table_ref}")
    project_id, dataset_id, table_name = parts
    table = client.dataset(dataset_id, project=project_id).table(table_name)

    inserted = 0
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        errors = client.insert_rows_json(table, chunk)
        if errors:
            raise RuntimeError(f"Errores insertando en BigQuery: {errors[:3]}")
        inserted += len(chunk)
    return inserted


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
