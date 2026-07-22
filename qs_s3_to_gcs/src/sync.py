"""
Listado S3 + prepare de manifiesto para Cloud Run Job multi-task.

Patrón nombre: AAABBB-YYYYMMDD-correlativo.(mp3|webm|...)
Modos (config sync.mode):
  - backfill_all
  - daily_last_n_days
  - daily_yesterday
"""

from __future__ import annotations

import json
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
    parse_audio_filename,
    resolve_date_window,
    resolve_sync_mode,
)
from manifest import write_manifest
from secrets_loader import load_aws_credentials


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
    objects: list[dict[str, Any]] = []
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix or ""):
        for obj in page.get("Contents") or []:
            key = obj["Key"]
            size = int(obj.get("Size") or 0)
            if size < min_size:
                continue
            if key.endswith("/"):
                continue
            objects.append(
                {
                    "key": key,
                    "size": size,
                    "last_modified": obj.get("LastModified"),
                    "file_name": basename_from_s3_key(key),
                }
            )
    objects.sort(key=lambda x: (x["file_name"], x["last_modified"]))
    return objects


def collect_candidates(config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Lista candidatos del día/ventana. Retorna (items, info)."""
    aws_cfg = config["aws"]
    sync_cfg = config.get("sync", {})
    batch_cfg = config.get("batch", {})
    secrets_cfg = config.get("secrets", {})

    mode = resolve_sync_mode(sync_cfg)
    date_start, date_end = resolve_date_window(sync_cfg, mode)
    target_date_str = format_date_window(date_start, date_end)
    filename_regex = sync_cfg.get("filename_regex", DEFAULT_FILENAME_REGEX)
    min_size = int(batch_cfg.get("min_object_size_bytes", 1))
    max_files = int(batch_cfg.get("max_files", 500))

    s3_client = build_s3_client(aws_cfg, secrets_cfg)
    s3_bucket = aws_cfg["bucket"]
    s3_prefix = aws_cfg.get("prefix", "")

    print(
        f"[prepare] mode={mode} date_window={target_date_str or 'ALL'} "
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
        # Serializa parsed para el manifiesto (fecha → ISO).
        item_out = {
            "key": item["key"],
            "size": item["size"],
            "file_name": item["file_name"],
            "parsed": {
                **parsed,
                "file_date": parsed["file_date"].isoformat(),
            },
        }
        candidates.append(item_out)

    if max_files > 0:
        candidates = candidates[:max_files]

    print(
        f"[prepare] s3_objects={len(all_objects)} candidates={len(candidates)} "
        f"rejected_name={rejected_name} rejected_date={rejected_date} "
        f"max_files={max_files}"
    )

    info = {
        "mode": mode,
        "target_date": target_date_str,
        "process_date": date_end.isoformat() if date_end else None,
        "scanned_s3": len(all_objects),
        "candidates": len(candidates),
        "rejected_name": rejected_name,
        "rejected_date": rejected_date,
    }
    return candidates, info


def run_prepare(config: dict[str, Any]) -> dict[str, Any]:
    """Genera manifiesto JSONL + meta en GCS. Exit 0 siempre que se escriba el meta."""
    gcp_cfg = config["gcp"]
    job_cfg = config.get("job", {})
    gcs_client = storage.Client(project=gcp_cfg.get("project_id"))
    gcs_bucket = gcp_cfg["bucket_name"]
    manifest_prefix = job_cfg.get("manifest_prefix", "state/manifests")
    state_object = gcp_cfg.get("state_object", "state/s3_to_gcs_last_sync.json")

    candidates, info = collect_candidates(config)
    process_date = info.get("process_date")
    if not process_date:
        # backfill: usar fecha UTC del prepare
        process_date = datetime.now(timezone.utc).date().isoformat()
        info["process_date"] = process_date

    # Rehidratar file_date string en parsed (ya ISO en manifiesto).
    meta = write_manifest(
        gcs_client,
        bucket=gcs_bucket,
        process_date=process_date,
        items=candidates,
        manifest_prefix=manifest_prefix,
        extra_meta={
            "mode": info["mode"],
            "target_date": info.get("target_date"),
            "scanned_s3": info["scanned_s3"],
            "rejected_name": info["rejected_name"],
            "rejected_date": info["rejected_date"],
        },
    )

    prior = read_state(gcs_client, gcs_bucket, state_object)
    new_state = dict(prior)
    new_state["last_run_utc"] = _utc_now_iso()
    new_state["last_mode"] = info["mode"]
    new_state["last_prepare_process_date"] = process_date
    new_state["last_manifest_count"] = meta["count"]
    new_state["last_manifest_object"] = meta["manifest_object"]
    write_state(gcs_client, gcs_bucket, state_object, new_state)

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


def parse_manifest_parsed(item: dict[str, Any], filename_regex: str) -> dict[str, Any]:
    """Convierte parsed del manifiesto (file_date ISO) a tipos runtime."""
    raw = item.get("parsed")
    if not raw:
        parsed = parse_audio_filename(item["file_name"], filename_regex)
        if not parsed:
            raise ValueError(f"nombre no parseable: {item.get('file_name')}")
        return parsed
    out = dict(raw)
    fd = out.get("file_date")
    if isinstance(fd, str):
        out["file_date"] = date.fromisoformat(fd)
    return out
