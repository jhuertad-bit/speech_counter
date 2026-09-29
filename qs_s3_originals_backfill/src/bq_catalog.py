"""Consulta catálogo BQ y UPDATE de gcs_original_*."""

from __future__ import annotations

from datetime import date
from typing import Any

from google.cloud import bigquery


def table_ref(project_id: str, dataset_id: str, table_id: str) -> str:
    return f"{project_id}.{dataset_id}.{table_id}"


def list_missing_originals(
    *,
    project_id: str,
    dataset_id: str,
    table_id: str,
    start: date,
    end: date,
    location: str = "US",
    max_files: int = 0,
) -> list[dict[str, Any]]:
    """
    Una fila por (fecha_audio, source_file_name) sin gcs_original_path.
    Segmentos FLAC comparten el mismo original.
    """
    ref = table_ref(project_id, dataset_id, table_id)
    limit_sql = f"\nLIMIT {int(max_files)}" if max_files and max_files > 0 else ""
    query = f"""
    SELECT
      CAST(fecha_audio AS STRING) AS fecha_audio,
      source_file_name,
      s3_key,
      ANY_VALUE(s3_uri) AS s3_uri,
      ANY_VALUE(file_size_bytes) AS file_size_bytes
    FROM (
      SELECT
        fecha_audio,
        NULLIF(TRIM(COALESCE(source_file_name, file_name)), '') AS source_file_name,
        NULLIF(TRIM(s3_key), '') AS s3_key,
        s3_uri,
        file_size_bytes
      FROM `{ref}`
      WHERE fecha_audio BETWEEN @start_date AND @end_date
        AND (gcs_original_path IS NULL OR TRIM(gcs_original_path) = '')
        AND NULLIF(TRIM(COALESCE(source_file_name, file_name)), '') IS NOT NULL
        AND NULLIF(TRIM(s3_key), '') IS NOT NULL
    )
    GROUP BY fecha_audio, source_file_name, s3_key
    ORDER BY fecha_audio, source_file_name
    {limit_sql}
    """
    client = bigquery.Client(project=project_id)
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start.isoformat()),
                bigquery.ScalarQueryParameter("end_date", "DATE", end.isoformat()),
            ]
        ),
        location=location,
    )
    rows: list[dict[str, Any]] = []
    for row in job.result():
        rows.append(
            {
                "fecha_audio": row.fecha_audio,
                "source_file_name": row.source_file_name,
                "s3_key": row.s3_key,
                "s3_uri": row.s3_uri,
                "file_size_bytes": int(row.file_size_bytes or 0),
            }
        )
    return rows


def update_original_paths(
    *,
    project_id: str,
    dataset_id: str,
    table_id: str,
    fecha_audio: str,
    source_file_name: str,
    s3_key: str,
    gcs_original_path: str,
    gcs_original_uri: str,
    location: str = "US",
) -> int:
    """Actualiza todas las filas del mismo audio (incl. segmentos). Retorna filas afectadas."""
    ref = table_ref(project_id, dataset_id, table_id)
    query = f"""
    UPDATE `{ref}`
    SET
      gcs_original_path = @gcs_original_path,
      gcs_original_uri = @gcs_original_uri
    WHERE fecha_audio = @fecha_audio
      AND (
        NULLIF(TRIM(s3_key), '') = @s3_key
        OR NULLIF(TRIM(COALESCE(source_file_name, file_name)), '') = @source_file_name
      )
      AND (gcs_original_path IS NULL OR TRIM(gcs_original_path) = '')
    """
    client = bigquery.Client(project=project_id)
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("gcs_original_path", "STRING", gcs_original_path),
                bigquery.ScalarQueryParameter("gcs_original_uri", "STRING", gcs_original_uri),
                bigquery.ScalarQueryParameter("fecha_audio", "DATE", fecha_audio),
                bigquery.ScalarQueryParameter("s3_key", "STRING", s3_key),
                bigquery.ScalarQueryParameter("source_file_name", "STRING", source_file_name),
            ]
        ),
        location=location,
    )
    job.result()
    return int(job.num_dml_affected_rows or 0)
