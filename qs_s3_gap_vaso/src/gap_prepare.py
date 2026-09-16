"""
Gap VASO — solo audios que el ingest legado omitía:

  (.audio) OR (len(prefijo Ticketero) != 6)

Anti-join: hist_queesmart_mp3_catalog + hist_queesmart_mp3_catalog_vaso.
Escribe manifiesto en state/gap_vaso_manifests/{date}.jsonl.

Flujo:
  1. gap_prepare (GAP_TARGET_DATE=YYYY-MM-DD)
  2. worker (SYNC_PROCESS_DATE=YYYY-MM-DD) → FLAC + catalog_vaso
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any

from google.cloud import bigquery, storage

from audio_paths import parse_audio_filename
from converter import file_stem
from gap_utils import GAP_SYNC_MODE, is_legacy_miss, resolve_gap_target_date
from manifest import write_manifest
from sync import build_s3_client, list_s3_objects
from worker import find_existing_gcs_object


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _table_ref(project_id: str, dataset_id: str, table_id: str) -> str:
    return f"{project_id}.{dataset_id}.{table_id}"


def _exclude_table_ids(config: dict[str, Any]) -> list[str]:
    bq_cfg = config.get("bigquery", {})
    ids = bq_cfg.get("catalog_exclude_table_ids")
    if ids:
        return [str(t) for t in ids if t]
    # Default: prod + vaso
    write_table = bq_cfg.get("table_id", "hist_queesmart_mp3_catalog_vaso")
    return ["hist_queesmart_mp3_catalog", write_table]


def fetch_catalog_s3_keys(
    config: dict[str, Any],
    target_date: date,
) -> set[str]:
    """s3_key ya catalogados (prod y/o vaso) para fecha_audio."""
    bq_cfg = config.get("bigquery", {})
    if not bq_cfg.get("enabled", True):
        return set()

    gcp_cfg = config["gcp"]
    project_id = gcp_cfg["project_id"]
    dataset_id = bq_cfg.get("dataset_id") or gcp_cfg.get("dataset_id")
    table_ids = _exclude_table_ids(config)
    client = bigquery.Client(project=project_id)
    location = bq_cfg.get("location", "US")

    keys: set[str] = set()
    for table_id in table_ids:
        table_ref = _table_ref(project_id, dataset_id, table_id)
        query = f"""
            SELECT DISTINCT s3_key
            FROM `{table_ref}`
            WHERE fecha_audio = @fecha_audio
              AND s3_key IS NOT NULL
        """
        try:
            rows = client.query(
                query,
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter(
                            "fecha_audio", "DATE", target_date
                        ),
                    ]
                ),
                location=location,
            ).result()
        except Exception as exc:  # noqa: BLE001
            # Tabla vaso puede no existir aún en el primer run
            print(f"[gap_prepare] WARN catalog skip {table_ref}: {exc}")
            continue
        keys.update(str(row.s3_key) for row in rows if row.s3_key)
    return keys


def collect_gap_candidates(
    config: dict[str, Any],
    target_date: date,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    aws_cfg = config["aws"]
    sync_cfg = config.get("sync", {})
    batch_cfg = config.get("batch", {})
    gcp_cfg = config["gcp"]
    secrets_cfg = config.get("secrets", {})
    # Sin filename_regex: parser flexible por guiones (5/7 chars + .audio)
    filename_pattern = None

    min_size = int(batch_cfg.get("min_object_size_bytes", 1))
    max_files = int(batch_cfg.get("max_files", 2000))
    gcs_prefix = gcp_cfg["destination_prefix"]
    date_folder_format = sync_cfg.get("gcs_date_folder_format", "%Y-%m-%d")

    gcs_client = storage.Client(project=gcp_cfg.get("project_id"))
    gcs_bucket = gcp_cfg["bucket_name"]
    catalog_keys = fetch_catalog_s3_keys(config, target_date)

    s3_client = build_s3_client(aws_cfg, secrets_cfg)
    all_objects = list_s3_objects(
        s3_client,
        aws_cfg["bucket"],
        aws_cfg.get("prefix", ""),
        min_size,
    )

    candidates: list[dict[str, Any]] = []
    rejected_name = 0
    rejected_date = 0
    rejected_not_legacy_miss = 0
    skipped_in_catalog = 0
    skipped_in_gcs = 0

    for item in all_objects:
        parsed = parse_audio_filename(item["file_name"], filename_pattern)
        if not parsed:
            rejected_name += 1
            continue
        if parsed["file_date"] != target_date:
            rejected_date += 1
            continue
        if not is_legacy_miss(parsed):
            rejected_not_legacy_miss += 1
            continue

        s3_key = item["key"]
        if s3_key in catalog_keys:
            skipped_in_catalog += 1
            continue

        stem = file_stem(item["file_name"])
        existing_gcs = find_existing_gcs_object(
            gcs_client,
            bucket=gcs_bucket,
            stem=stem,
            file_date=target_date,
            gcs_prefix=gcs_prefix,
            date_folder_format=date_folder_format,
        )
        if existing_gcs:
            skipped_in_gcs += 1
            continue

        candidates.append(
            {
                "key": s3_key,
                "size": item["size"],
                "file_name": item["file_name"],
                "parsed": {
                    **parsed,
                    "file_date": parsed["file_date"].isoformat(),
                },
            }
        )

    candidates.sort(key=lambda x: x["file_name"])
    if max_files > 0:
        truncated = max(0, len(candidates) - max_files)
        candidates = candidates[:max_files]
    else:
        truncated = 0

    info = {
        "role": "gap_prepare",
        "job": "qs_s3_gap_vaso",
        "sync_mode": GAP_SYNC_MODE,
        "filter": "legacy_miss (.audio OR prefix_len!=6)",
        "target_date": target_date.isoformat(),
        "process_date": target_date.isoformat(),
        "scanned_s3": len(all_objects),
        "catalog_keys": len(catalog_keys),
        "catalog_exclude_tables": _exclude_table_ids(config),
        "candidates": len(candidates),
        "rejected_name": rejected_name,
        "rejected_date": rejected_date,
        "rejected_not_legacy_miss": rejected_not_legacy_miss,
        "skipped_in_catalog": skipped_in_catalog,
        "skipped_in_gcs": skipped_in_gcs,
        "truncated_by_max_files": truncated,
        "max_files": max_files,
        "prepared_at": _utc_now_iso(),
    }
    return candidates, info


def run_gap_prepare(config: dict[str, Any]) -> dict[str, Any]:
    gcp_cfg = config["gcp"]
    job_cfg = config.get("job", {})
    gap_cfg = config.get("gap", {})
    manifest_prefix = (
        gap_cfg.get("manifest_prefix")
        or job_cfg.get("manifest_prefix")
        or "state/gap_vaso_manifests"
    )

    target_date = resolve_gap_target_date(config)
    gcs_client = storage.Client(project=gcp_cfg.get("project_id"))
    gcs_bucket = gcp_cfg["bucket_name"]

    print(
        f"[qs_s3_gap_vaso] gap_prepare target_date={target_date.isoformat()} "
        f"manifest_prefix={manifest_prefix}"
    )

    candidates, info = collect_gap_candidates(config, target_date)
    process_date = target_date.isoformat()

    meta = write_manifest(
        gcs_client,
        bucket=gcs_bucket,
        process_date=process_date,
        items=candidates,
        manifest_prefix=manifest_prefix,
        extra_meta=info,
    )

    summary = {
        "status": "ok",
        **info,
        "manifest_count": meta["count"],
        "manifest_object": meta["manifest_object"],
        "meta_object": meta["meta_object"],
    }
    print(json.dumps(summary, indent=2))
    return summary
