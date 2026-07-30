"""Prepare: lista URIs del día desde enriched → manifiesto GCS."""

from __future__ import annotations

import json
from typing import Any

from google.cloud import bigquery, storage

from config_loader import process_date_from_env
from manifest import write_manifest

# Shape alineado a tmp_queuesmart_mp3_audios del SP gen_ia (enriched).
_SELECT_COLS = """
  process_day AS process_date,
  gcs_uri,
  file_name,
  source_file_name,
  audio,
  recordid,
  rowid,
  codagencia,
  CAST(NULL AS STRING) AS gcs_path,
  campus_code,
  type_code,
  correlative,
  file_size_bytes,
  duration_seconds,
  CAST(NULL AS STRING) AS sync_mode,
  convert_method,
  CAST(NULL AS STRING) AS s3_uri,
  match_status,
  asesornombre,
  asesorusuario,
  asesorcodigo,
  ndoc,
  nombresusuario,
  numcelular,
  clientetipo,
  `database`
"""


def run_prepare(config: dict[str, Any]) -> dict[str, Any]:
    process_date = process_date_from_env(config)
    gcp = config["gcp"]
    bq_cfg = config["bigquery"]
    job_cfg = config.get("job", {})
    manifest_prefix = job_cfg.get("manifest_prefix", "state/stt_manifests")
    enriched = bq_cfg["enriched_table"]

    print(f"[prepare] process_date={process_date} table={enriched}")

    client = bigquery.Client(project=gcp["project_id"], location=bq_cfg.get("location", "US"))
    sql = f"""
      SELECT {_SELECT_COLS}
      FROM `{enriched}`
      WHERE process_day = @process_date
        AND match_status IN ('BOTH', 'GCS_ONLY')
        AND gcs_uri IS NOT NULL
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY gcs_uri
        ORDER BY catalog_fecha_procesamiento DESC
      ) = 1
      ORDER BY catalog_fecha_procesamiento DESC
    """
    job = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("process_date", "DATE", process_date),
            ]
        ),
    )
    items = [dict(row.items()) for row in job.result()]
    # Fechas/DATE → str para JSON
    for it in items:
        if it.get("process_date") is not None:
            it["process_date"] = str(it["process_date"])

    gcs = storage.Client(project=gcp["project_id"])
    meta = write_manifest(
        gcs,
        bucket=gcp["bucket_name"],
        process_date=process_date,
        manifest_prefix=manifest_prefix,
        items=items,
    )
    print(json.dumps({"role": "prepare", "status": "ok", **meta}, indent=2))
    return meta
