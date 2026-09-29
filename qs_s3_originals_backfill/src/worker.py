"""Worker: copia S3 → GCS original/ y UPDATE catálogo BQ."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from google.cloud import storage

from bq_catalog import update_original_paths
from media_io import gcs_blob_exists, stream_file_to_gcs, stream_s3_to_file
from paths import guess_content_type
from secrets_loader import load_aws_credentials


def build_s3_client(aws_cfg: dict[str, Any], secrets_cfg: dict[str, Any]):
    access_key, secret_key = load_aws_credentials(secrets_cfg)
    if not access_key or not secret_key:
        raise ValueError("Credenciales AWS no encontradas (env o Secret Manager)")
    session = boto3.session.Session(
        region_name=aws_cfg["region"],
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    kwargs: dict[str, Any] = {
        "config": BotoConfig(retries={"max_attempts": 5, "mode": "standard"}),
    }
    if aws_cfg.get("endpoint_url"):
        kwargs["endpoint_url"] = aws_cfg["endpoint_url"]
    return session.client("s3", **kwargs)


def process_one(
    *,
    config: dict[str, Any],
    s3_client,
    gcs_client: storage.Client,
    item: dict[str, Any],
) -> dict[str, Any]:
    aws = config["aws"]
    gcp = config["gcp"]
    sync = config.get("sync", {})
    batch = config.get("batch", {})
    bq = config.get("bigquery", {})

    s3_bucket = aws["bucket"]
    gcs_bucket = gcp["bucket_name"]
    s3_key = item["s3_key"]
    source_name = item["source_file_name"]
    fecha_audio = str(item["fecha_audio"])[:10]
    gcs_key = item["gcs_original_path"]
    gcs_uri = item.get("gcs_original_uri") or f"gs://{gcs_bucket}/{gcs_key}"
    chunk = int(batch.get("io_chunk_size_bytes", 8 * 1024 * 1024))
    skip_if_exists = bool(sync.get("skip_if_exists_in_gcs", True))

    result: dict[str, Any] = {
        "s3_key": s3_key,
        "source_file_name": source_name,
        "fecha_audio": fecha_audio,
        "gcs_original_path": gcs_key,
        "status": "error",
    }

    already = skip_if_exists and gcs_blob_exists(gcs_client, gcs_bucket, gcs_key)
    if already:
        print(f"[worker] already gs://{gcs_bucket}/{gcs_key}")
        result["action"] = "skip_exists"
    else:
        with tempfile.TemporaryDirectory(prefix="qs_orig_bf_") as tmpdir:
            _, ext = os.path.splitext(source_name)
            local_src = os.path.join(tmpdir, f"source{ext or '.bin'}")
            print(f"[worker] download s3://{s3_bucket}/{s3_key}")
            size = stream_s3_to_file(
                s3_client,
                bucket=s3_bucket,
                key=s3_key,
                dest_path=local_src,
                chunk_size=chunk,
            )
            uploaded = stream_file_to_gcs(
                gcs_client,
                local_path=local_src,
                bucket=gcs_bucket,
                blob_name=gcs_key,
                content_type=guess_content_type(source_name),
                chunk_size=chunk,
            )
            result["bytes"] = uploaded or size
            result["action"] = "copied"
            print(f"[worker] OK gs://{gcs_bucket}/{gcs_key} bytes={result['bytes']}")

    updated = update_original_paths(
        project_id=gcp["project_id"],
        dataset_id=bq.get("dataset_id") or gcp.get("dataset_id") or "raw_queue_smart",
        table_id=bq.get("table_id", "hist_queesmart_mp3_catalog"),
        fecha_audio=fecha_audio,
        source_file_name=source_name,
        s3_key=s3_key,
        gcs_original_path=gcs_key,
        gcs_original_uri=gcs_uri,
        location=bq.get("location", "US"),
    )
    result["bq_updated"] = updated
    result["gcs_original_uri"] = gcs_uri
    result["status"] = "ok"
    return result
