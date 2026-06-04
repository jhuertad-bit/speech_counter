"""BigQuery para reporte_whatsapp_documento_raw (medios descargachats)."""

from __future__ import annotations

import json
import os
from typing import Any

from google.cloud import bigquery


def load_schema(table_name: str = "reporte_whatsapp_documento_raw") -> list[dict[str, Any]]:
    schema_path = os.path.join(os.path.dirname(__file__), "tablas", f"{table_name}.json")
    with open(schema_path, "r", encoding="utf-8") as handle:
        schema = json.load(handle)
    if not any(field["name"] == "fecha_evento" for field in schema):
        raise ValueError("El esquema debe incluir fecha_evento")
    return schema


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
    partition_field: str = "fecha_evento",
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
        dataset.location = "US"
        client.create_dataset(dataset, timeout=30)

    table = bigquery.Table(table_ref, schema=schema_fields(schema))
    table.time_partitioning = bigquery.TimePartitioning(
        type_=bigquery.TimePartitioningType.DAY,
        field=partition_field,
    )
    client.create_table(table)
    return table_ref


def delete_partition(
    client: bigquery.Client,
    table_ref: str,
    fecha_evento: str,
    partition_field: str = "fecha_evento",
) -> None:
    partition_date = fecha_evento.replace("-", "")
    partition_id = f"{table_ref}${partition_date}"
    try:
        client.delete_table(partition_id)
        print(f"Partición eliminada: {partition_id}")
    except Exception as exc:
        error_str = str(exc).lower()
        if "not found" in error_str or "404" in error_str:
            print(f"Sin partición previa para {fecha_evento}")
        else:
            query = f"""
                DELETE FROM `{table_ref}`
                WHERE {partition_field} = @fecha_evento
            """
            client.query(
                query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("fecha_evento", "DATE", fecha_evento),
                    ]
                ),
            ).result()


def insert_rows(
    client: bigquery.Client,
    dataset_id: str,
    table_id: str,
    rows: list[dict[str, Any]],
    batch_size: int = 500,
) -> None:
    if not rows:
        return
    table_ref = client.dataset(dataset_id).table(table_id)
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        errors = client.insert_rows_json(table_ref, chunk)
        if errors:
            raise RuntimeError(f"Errores insertando en BigQuery: {errors[:3]}")
