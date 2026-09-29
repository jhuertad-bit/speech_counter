"""Prepare: lista pendientes en BQ y escribe manifiesto JSONL en GCS."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from google.cloud import storage

from bq_catalog import list_missing_originals
from manifest import write_manifest
from paths import gcs_key_for_original, resolve_date_range, run_id_for_range


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_prepare(config: dict[str, Any]) -> dict[str, Any]:
    gcp = config["gcp"]
    aws = config["aws"]
    sync = config.get("sync", {})
    batch = config.get("batch", {})
    bq = config.get("bigquery", {})
    job_cfg = config.get("job", {})

    start, end = resolve_date_range(sync)
    process_date = run_id_for_range(start, end)
    max_files = int(batch.get("max_files") or 0)

    print(f"[prepare] BQ pendientes originales {start} .. {end}")
    rows = list_missing_originals(
        project_id=gcp["project_id"],
        dataset_id=bq.get("dataset_id") or gcp.get("dataset_id") or "raw_queue_smart",
        table_id=bq.get("table_id", "hist_queesmart_mp3_catalog"),
        start=start,
        end=end,
        location=bq.get("location", "US"),
        max_files=max_files,
    )

    gcs_prefix = gcp["destination_prefix"]
    date_fmt = sync.get("gcs_date_folder_format", "%Y-%m-%d")
    original_subdir = sync.get("original_subdir", "original")
    s3_bucket = aws["bucket"]

    items: list[dict[str, Any]] = []
    for row in rows:
        src_name = row["source_file_name"]
        fecha = row["fecha_audio"]
        gcs_key = gcs_key_for_original(
            src_name,
            fecha,
            gcs_prefix,
            date_folder_format=date_fmt,
            original_subdir=original_subdir,
        )
        items.append(
            {
                "s3_key": row["s3_key"],
                "s3_uri": row.get("s3_uri") or f"s3://{s3_bucket}/{row['s3_key']}",
                "source_file_name": src_name,
                "fecha_audio": fecha,
                "file_size_bytes": row.get("file_size_bytes") or 0,
                "gcs_original_path": gcs_key,
                "gcs_original_uri": f"gs://{gcp['bucket_name']}/{gcs_key}",
            }
        )

    gcs_client = storage.Client(project=gcp.get("project_id"))
    gcs_bucket = gcp["bucket_name"]
    manifest_prefix = job_cfg.get("manifest_prefix", "state/manifests_originals_backfill")

    meta = write_manifest(
        gcs_client,
        bucket=gcs_bucket,
        process_date=process_date,
        items=items,
        manifest_prefix=manifest_prefix,
        extra_meta={
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "s3_bucket": s3_bucket,
            "scanned": len(rows),
        },
    )

    state_object = gcp.get("state_object", "state/s3_originals_backfill_last.json")
    gcs_client.bucket(gcs_bucket).blob(state_object).upload_from_string(
        json.dumps(
            {
                "updated_at_utc": _utc_now_iso(),
                "last_prepare_process_date": process_date,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "last_manifest_count": meta["count"],
                "last_manifest_object": meta["manifest_object"],
            },
            indent=2,
        ),
        content_type="application/json",
    )

    summary = {
        "role": "prepare",
        "status": "ok",
        "process_date": process_date,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "count": meta["count"],
        "manifest_object": meta["manifest_object"],
        "meta_object": meta["meta_object"],
    }
    print(json.dumps(summary, indent=2))
    return summary
