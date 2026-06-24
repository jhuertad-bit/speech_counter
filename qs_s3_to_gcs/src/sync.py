"""
Micro-batch: copia audios S3 → GCS con carpetas por fecha del nombre de archivo.

Patrón esperado: AAABBB-YYYYMMDD-correlativo.mp3 (ej. 015AD1-20260217-123728.mp3)

Modos (config sync.mode):
  - backfill_all:       todos los MP3 históricos
  - daily_last_n_days:  últimos N días (fecha en nombre), default N=15 — prueba
  - daily_yesterday:    solo ayer (scheduler producción)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from google.cloud import storage

from audio_paths import (
    DEFAULT_FILENAME_REGEX,
    basename_from_s3_key,
    file_date_in_window,
    format_date_window,
    gcs_key_for_audio,
    parse_audio_filename,
    resolve_date_window,
    resolve_sync_mode,
)
from bq_catalog import build_catalog_row, catalog_files
from secrets_loader import load_aws_credentials


@dataclass
class SyncResult:
    scanned: int
    copied: int
    skipped: int
    bytes_copied: int
    errors: list[str]
    watermark_before: str | None
    watermark_after: str | None
    mode: str = ""
    target_date: str | None = None
    already_in_gcs: int = 0
    bq_inserted: int = 0
    bq_cataloged: int = 0


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_s3_client(aws_cfg: dict[str, Any], secrets_cfg: dict[str, Any]):
    access_key, secret_key = load_aws_credentials(secrets_cfg)
    session_kwargs: dict[str, Any] = {"region_name": aws_cfg["region"]}
    if access_key and secret_key:
        session_kwargs["aws_access_key_id"] = access_key
        session_kwargs["aws_secret_access_key"] = secret_key
    else:
        raise ValueError(
            "Credenciales AWS no encontradas. Configure env vars o Secret Manager "
            "(secrets.source=secret_manager en config.json)."
        )

    session = boto3.session.Session(**session_kwargs)
    client_kwargs: dict[str, Any] = {
        "config": BotoConfig(retries={"max_attempts": 5, "mode": "standard"})
    }
    if aws_cfg.get("endpoint_url"):
        client_kwargs["endpoint_url"] = aws_cfg["endpoint_url"]

    return session.client("s3", **client_kwargs)


def read_state(gcs_client: storage.Client, bucket: str, state_object: str) -> dict[str, Any]:
    blob = gcs_client.bucket(bucket).blob(state_object)
    if not blob.exists():
        return {}
    return json.loads(blob.download_as_text(encoding="utf-8"))


def write_state(
    gcs_client: storage.Client,
    bucket: str,
    state_object: str,
    state: dict[str, Any],
) -> None:
    payload = {"updated_at_utc": _utc_now_iso(), **state}
    gcs_client.bucket(bucket).blob(state_object).upload_from_string(
        json.dumps(payload, indent=2),
        content_type="application/json",
    )


def list_s3_objects(
    s3_client,
    bucket: str,
    prefix: str,
    min_size: int,
) -> list[dict[str, Any]]:
    paginator = s3_client.get_paginator("list_objects_v2")
    objects: list[dict[str, Any]] = []

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if key.endswith("/"):
                continue
            size = int(item.get("Size", 0))
            if size < min_size:
                continue
            last_modified = item["LastModified"]
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)
            objects.append(
                {
                    "key": key,
                    "size": size,
                    "last_modified": last_modified,
                    "file_name": basename_from_s3_key(key),
                }
            )

    objects.sort(key=lambda x: (x["file_name"], x["last_modified"]))
    return objects


def gcs_blob_exists(gcs_client: storage.Client, bucket: str, gcs_key: str) -> bool:
    return gcs_client.bucket(bucket).blob(gcs_key).exists()


def copy_s3_object_to_gcs(
    s3_client,
    gcs_client: storage.Client,
    s3_bucket: str,
    s3_key: str,
    gcs_bucket: str,
    gcs_key: str,
) -> int:
    response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
    blob = gcs_client.bucket(gcs_bucket).blob(gcs_key)
    content_type = response.get("ContentType") or "audio/mpeg"
    blob.upload_from_file(
        response["Body"],
        content_type=content_type,
        rewind=True,
    )
    return int(response.get("ContentLength") or 0)


def run_micro_batch(config: dict[str, Any]) -> SyncResult:
    aws_cfg = config["aws"]
    gcp_cfg = config["gcp"]
    batch_cfg = config["batch"]
    sync_cfg = config.get("sync", {})
    secrets_cfg = config.get("secrets", {})

    mode = resolve_sync_mode(sync_cfg)
    date_start, date_end = resolve_date_window(sync_cfg, mode)
    target_date_str = format_date_window(date_start, date_end)

    filename_regex = sync_cfg.get("filename_regex", DEFAULT_FILENAME_REGEX)
    date_folder_format = sync_cfg.get("gcs_date_folder_format", "%Y-%m-%d")
    skip_if_exists = bool(sync_cfg.get("skip_if_exists_in_gcs", True))

    s3_client = build_s3_client(aws_cfg, secrets_cfg)
    gcs_client = storage.Client(project=gcp_cfg.get("project_id"))

    s3_bucket = aws_cfg["bucket"]
    s3_prefix = aws_cfg.get("prefix", "")
    gcs_bucket = gcp_cfg["bucket_name"]
    gcs_prefix = gcp_cfg["destination_prefix"]
    state_object = gcp_cfg["state_object"]

    max_files = int(batch_cfg.get("max_files", 50))
    max_total_bytes = int(batch_cfg.get("max_total_mb", 500)) * 1024 * 1024
    min_size = int(batch_cfg.get("min_object_size_bytes", 1))

    prior_state = read_state(gcs_client, gcs_bucket, state_object)
    watermark_before = prior_state.get("last_daily_date") or prior_state.get("last_modified_utc")

    print(
        f"[sync] mode={mode} date_window={target_date_str or 'ALL'} "
        f"prefix=s3://{s3_bucket}/{s3_prefix}"
    )

    all_objects = list_s3_objects(s3_client, s3_bucket, s3_prefix, min_size)
    candidates: list[dict[str, Any]] = []
    rejected_name = 0
    rejected_date = 0

    for item in all_objects:
        parsed = parse_audio_filename(item["file_name"], filename_regex)
        if not parsed:
            rejected_name += 1
            continue
        if not file_date_in_window(parsed["file_date"], date_start, date_end):
            rejected_date += 1
            continue
        item["parsed"] = parsed
        candidates.append(item)

    print(
        f"[sync] s3_objects={len(all_objects)} candidates={len(candidates)} "
        f"rejected_name={rejected_name} rejected_date={rejected_date}"
    )

    copied = 0
    skipped = 0
    already_in_gcs = 0
    bytes_copied = 0
    errors: list[str] = []
    catalog_rows: list[dict[str, Any]] = []
    processed_at = datetime.now(timezone.utc)

    bq_cfg = config.get("bigquery", {})
    bq_enabled = bool(bq_cfg.get("enabled", True))
    catalog_existing = bool(bq_cfg.get("catalog_existing_in_gcs", True))

    for item in candidates:
        if copied >= max_files:
            skipped += 1
            continue
        if bytes_copied >= max_total_bytes:
            skipped += 1
            continue

        parsed = item["parsed"]
        s3_key = item["key"]
        file_name = parsed["file_name"]
        file_date: date = parsed["file_date"]
        gcs_key = gcs_key_for_audio(
            file_name,
            file_date,
            gcs_prefix,
            date_folder_format=date_folder_format,
        )

        if skip_if_exists and gcs_blob_exists(gcs_client, gcs_bucket, gcs_key):
            already_in_gcs += 1
            if bq_enabled and catalog_existing:
                catalog_rows.append(
                    build_catalog_row(
                        parsed=parsed,
                        gcs_bucket=gcs_bucket,
                        gcs_key=gcs_key,
                        s3_bucket=s3_bucket,
                        s3_key=s3_key,
                        file_size_bytes=int(item["size"]),
                        sync_mode=mode,
                        processed_at=processed_at,
                    )
                )
            continue

        try:
            size = copy_s3_object_to_gcs(
                s3_client,
                gcs_client,
                s3_bucket,
                s3_key,
                gcs_bucket,
                gcs_key,
            )
            copied += 1
            bytes_copied += size
            if bq_enabled:
                catalog_rows.append(
                    build_catalog_row(
                        parsed=parsed,
                        gcs_bucket=gcs_bucket,
                        gcs_key=gcs_key,
                        s3_bucket=s3_bucket,
                        s3_key=s3_key,
                        file_size_bytes=size,
                        sync_mode=mode,
                        processed_at=processed_at,
                    )
                )
            print(
                f"OK s3://{s3_bucket}/{s3_key} -> gs://{gcs_bucket}/{gcs_key} "
                f"({size} bytes, campus={parsed['campus']}, type={parsed['type_code']})"
            )
        except Exception as exc:  # noqa: BLE001
            msg = f"{s3_key}: {exc}"
            errors.append(msg)
            print(f"ERROR {msg}")

    bq_inserted = 0
    if bq_enabled and catalog_rows:
        try:
            bq_inserted = catalog_files(
                project_id=gcp_cfg["project_id"],
                dataset_id=bq_cfg.get("dataset_id", "raw_queuesmart"),
                table_id=bq_cfg.get("table_id", "hist_queesmart_mp3_catalog"),
                rows=catalog_rows,
                location=bq_cfg.get("location", "us-central1"),
            )
            print(f"[bq] cataloged={len(catalog_rows)} inserted={bq_inserted}")
        except Exception as exc:  # noqa: BLE001
            msg = f"bigquery: {exc}"
            errors.append(msg)
            print(f"ERROR {msg}")

    new_state = dict(prior_state)
    new_state["last_run_utc"] = _utc_now_iso()
    new_state["last_mode"] = mode
    new_state["files_copied_last_run"] = copied
    new_state["bytes_copied_last_run"] = bytes_copied
    new_state["already_in_gcs_last_run"] = already_in_gcs
    new_state["bq_inserted_last_run"] = bq_inserted

    if mode in {"daily_yesterday", "daily_last_n_days"} and date_end and copied > 0:
        new_state["last_daily_date"] = date_end.isoformat()
        new_state["last_date_window"] = target_date_str
    if mode == "backfill_all" and copied == 0 and already_in_gcs > 0 and not errors:
        new_state["backfill_complete"] = True

    write_state(gcs_client, gcs_bucket, state_object, new_state)
    watermark_after = new_state.get("last_daily_date") or new_state.get("last_run_utc")

    return SyncResult(
        scanned=len(candidates),
        copied=copied,
        skipped=skipped,
        bytes_copied=bytes_copied,
        errors=errors,
        watermark_before=watermark_before,
        watermark_after=watermark_after,
        mode=mode,
        target_date=target_date_str,
        already_in_gcs=already_in_gcs,
        bq_inserted=bq_inserted,
        bq_cataloged=len(catalog_rows),
    )
