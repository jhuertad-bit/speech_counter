"""Llamadas a stored procedures de BigQuery desde el Cloud Run Job."""

from __future__ import annotations

from datetime import date
from typing import Any

from google.cloud import bigquery


def call_procedure(
    *,
    project_id: str,
    procedure_id: str,
    args: list[Any],
    location: str = "US",
) -> None:
    """
    Ejecuta CALL `procedure_id`(args...).

    procedure_id: project.dataset.procedure (sin backticks).
    """
    client = bigquery.Client(project=project_id, location=location)
    placeholders = ", ".join(f"@a{i}" for i in range(len(args)))
    query = f"CALL `{procedure_id}`({placeholders})"

    params: list[bigquery.ScalarQueryParameter] = []
    for i, value in enumerate(args):
        if isinstance(value, date) and not hasattr(value, "hour"):
            params.append(bigquery.ScalarQueryParameter(f"a{i}", "DATE", value))
        elif value is None:
            params.append(bigquery.ScalarQueryParameter(f"a{i}", "STRING", None))
        elif isinstance(value, str):
            params.append(bigquery.ScalarQueryParameter(f"a{i}", "STRING", value))
        elif isinstance(value, int):
            params.append(bigquery.ScalarQueryParameter(f"a{i}", "INT64", value))
        else:
            raise TypeError(f"Tipo de argumento no soportado para CALL: {type(value)}")

    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(query_parameters=params),
        location=location,
    )
    job.result()
