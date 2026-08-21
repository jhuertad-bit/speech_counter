"""Prepare: lista GCS origen del día y escribe manifiesto en el bucket destino."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from dates import dest_object_name, resolve_process_date, source_list_prefix
from gcs_copy import list_source_objects, source_storage_client, storage_client
from manifest import write_manifest


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_candidates(config: dict[str, Any], process_date: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    src_cfg = config["source"]
    dest_cfg = config["dest"]
    sync_cfg = config.get("sync", {})
    batch_cfg = config.get("batch", {})
    min_size = int(batch_cfg.get("min_object_size_bytes", 1))
    max_files = int(batch_cfg.get("max_files", 5000))

    list_prefix = source_list_prefix(src_cfg.get("prefix", ""), process_date, sync_cfg)
    src_client = source_storage_client(config)
    raw = list_source_objects(src_client, src_cfg["bucket_name"], list_prefix, min_size)
    dest_prefix = dest_cfg.get("destination_prefix", "")
    src_prefix = src_cfg.get("prefix", "")

    candidates: list[dict[str, Any]] = []
    for item in raw:
        dest_key = dest_object_name(item["key"], src_prefix, dest_prefix)
        candidates.append(
            {
                "key": item["key"],
                "size": item["size"],
                "file_name": item["file_name"],
                "content_type": item.get("content_type"),
                "dest_key": dest_key,
                "src_uri": f"gs://{src_cfg['bucket_name']}/{item['key']}",
                "dst_uri": f"gs://{dest_cfg['bucket_name']}/{dest_key}",
            }
        )
    if max_files > 0:
        candidates = candidates[:max_files]

    info = {
        "mode": str(sync_cfg.get("mode") or "daily_yesterday"),
        "process_date": process_date,
        "list_prefix": list_prefix,
        "scanned": len(raw),
        "candidates": len(candidates),
    }
    print(
        f"[prepare] gs://{src_cfg['bucket_name']}/{list_prefix} "
        f"scanned={len(raw)} candidates={len(candidates)}"
    )
    return candidates, info


def run_prepare(config: dict[str, Any]) -> dict[str, Any]:
    dest_cfg = config["dest"]
    job_cfg = config.get("job", {})
    process_date = resolve_process_date(config)
    dest_client = storage_client(dest_cfg["project_id"])
    dest_bucket = dest_cfg["bucket_name"]
    manifest_prefix = job_cfg.get("manifest_prefix", "state/manifests")

    candidates, info = collect_candidates(config, process_date)
    meta = write_manifest(
        dest_client,
        bucket=dest_bucket,
        process_date=process_date,
        items=candidates,
        manifest_prefix=manifest_prefix,
        extra_meta={
            "mode": info["mode"],
            "list_prefix": info["list_prefix"],
            "scanned": info["scanned"],
            "source_project": config["source"]["project_id"],
            "source_bucket": config["source"]["bucket_name"],
        },
    )

    state_object = dest_cfg.get("state_object", "state/gcs_copy_last_sync.json")
    dest_client.bucket(dest_bucket).blob(state_object).upload_from_string(
        json.dumps(
            {
                "updated_at_utc": _utc_now_iso(),
                "last_prepare_process_date": process_date,
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
        **info,
        "manifest_count": meta["count"],
        "manifest_object": meta["manifest_object"],
        "meta_object": meta["meta_object"],
    }
    print(json.dumps(summary, indent=2))
    return summary
