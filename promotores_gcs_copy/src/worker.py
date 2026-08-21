"""Worker: 1 task = 1 objeto del manifiesto (copy GCS→GCS + ffprobe + catálogo BQ)."""

from __future__ import annotations

from typing import Any

from bq_catalog import catalog_one
from dates import resolve_process_date
from gcs_copy import copy_object, dest_exists, source_storage_client, source_uses_sa_json, storage_client
from probe_audio import probe_gcs_blob, probe_to_dict


def process_one(config: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    src_cfg = config["source"]
    dest_cfg = config["dest"]
    skip_if_exists = bool(config.get("sync", {}).get("skip_if_exists_in_dest", True))
    process_date = resolve_process_date(config)

    src_key = item["key"]
    dest_key = item.get("dest_key")
    if not dest_key:
        raise ValueError(f"manifiesto sin dest_key: {src_key}")

    src_client = source_storage_client(config)
    dst_client = storage_client(dest_cfg["project_id"])
    src_bucket = src_cfg["bucket_name"]
    dst_bucket = dest_cfg["bucket_name"]

    copy_result = "copied"
    size: int | None = None

    if skip_if_exists and dest_exists(dst_client, dst_bucket, dest_key):
        copy_result = "already_in_gcs"
        size = int(item.get("size") or 0) or None
    else:
        size = copy_object(
            src_client,
            dst_client,
            src_bucket=src_bucket,
            src_key=src_key,
            dst_bucket=dst_bucket,
            dst_key=dest_key,
            use_stream=source_uses_sa_json(config),
        )

    probe_fields: dict[str, Any] = probe_to_dict(None)
    try:
        probe = probe_gcs_blob(dst_client, dst_bucket, dest_key)
        probe_fields = probe_to_dict(probe)
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] ffprobe skip {dest_key}: {type(exc).__name__}: {exc}")

    catalog_meta = catalog_one(
        config,
        process_date=process_date,
        dest_key=dest_key,
        source_key=src_key,
        file_size_bytes=size,
        copy_result=copy_result,
        content_type=item.get("content_type"),
        **probe_fields,
    )

    out: dict[str, Any] = {
        "status": "ok",
        "result": copy_result,
        "src_uri": f"gs://{src_bucket}/{src_key}",
        "dst_uri": f"gs://{dst_bucket}/{dest_key}",
        **probe_fields,
        **catalog_meta,
    }
    if size is not None:
        out["bytes"] = size
    return out
