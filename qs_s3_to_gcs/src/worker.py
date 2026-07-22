"""Procesa un ítem del manifiesto: S3 → (pass-through | FLAC) → GCS → BigQuery."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from typing import Any

from google.cloud import storage

from audio_paths import gcs_key_for_audio, parse_audio_filename
from bq_catalog import build_catalog_row, catalog_files
from converter import (
    DEFAULT_NOISE_FILTER,
    DEFAULT_VOICE_FILTER,
    KNOWN_STORAGE_EXTS,
    build_audio_filter,
    decide_action,
    extension_for_action,
    file_stem,
    probe_media,
    storage_file_name,
    transcode_to_flac,
)
from media_io import copy_file, stream_file_to_gcs, stream_s3_to_file


# Errores de media ilegible → skip permanente (no tumba el batch si se registra aparte).
UNCONVERTIBLE_MARKERS = (
    "invalid as first byte of an EBML number",
    "Error opening input",
    "End of file",
    "Invalid data found when processing input",
    "archivo vacío en S3",
    "Input vacío o inexistente",
    "FLAC output is empty",
    "ffprobe failed",
)


def is_unconvertible_error(exc: BaseException) -> bool:
    text = str(exc)
    return any(marker in text for marker in UNCONVERTIBLE_MARKERS)


def gcs_blob_exists(gcs_client: storage.Client, bucket: str, gcs_key: str) -> bool:
    return gcs_client.bucket(bucket).blob(gcs_key).exists()


def find_existing_gcs_object(
    gcs_client: storage.Client,
    *,
    bucket: str,
    stem: str,
    file_date,
    gcs_prefix: str,
    date_folder_format: str,
) -> str | None:
    """Busca objeto ya subido (legacy .mp3 u extensión real). Retorna gcs_key o None."""
    for ext in KNOWN_STORAGE_EXTS:
        key = gcs_key_for_audio(
            storage_file_name(stem, ext),
            file_date,
            gcs_prefix,
            date_folder_format=date_folder_format,
        )
        if gcs_blob_exists(gcs_client, bucket, key):
            return key
    return None


def process_one_candidate(
    *,
    config: dict[str, Any],
    s3_client,
    gcs_client: storage.Client,
    item: dict[str, Any],
    sync_mode: str,
) -> dict[str, Any]:
    """
    Procesa un candidato del manifiesto.

    Retorna dict con status: ok | already_in_gcs | skipped_corrupt | error
    """
    aws_cfg = config["aws"]
    gcp_cfg = config["gcp"]
    sync_cfg = config.get("sync", {})
    audio_cfg = config.get("audio", {})
    bq_cfg = config.get("bigquery", {})

    s3_bucket = aws_cfg["bucket"]
    gcs_bucket = gcp_cfg["bucket_name"]
    gcs_prefix = gcp_cfg["destination_prefix"]
    date_folder_format = sync_cfg.get("gcs_date_folder_format", "%Y-%m-%d")
    skip_if_exists = bool(sync_cfg.get("skip_if_exists_in_gcs", True))
    filename_regex = sync_cfg.get("filename_regex")

    s3_key = item["key"]
    source_name = item.get("file_name") or os.path.basename(s3_key)
    parsed = item.get("parsed") or parse_audio_filename(source_name, filename_regex)
    if not parsed:
        raise ValueError(f"nombre no parseable: {source_name}")

    stem = file_stem(source_name)
    processed_at = datetime.now(timezone.utc)
    result: dict[str, Any] = {
        "s3_key": s3_key,
        "source_file_name": source_name,
        "status": "error",
    }

    if skip_if_exists:
        existing_key = find_existing_gcs_object(
            gcs_client,
            bucket=gcs_bucket,
            stem=stem,
            file_date=parsed["file_date"],
            gcs_prefix=gcs_prefix,
            date_folder_format=date_folder_format,
        )
        if existing_key:
            print(f"[worker] SKIP already_in_gcs gs://{gcs_bucket}/{existing_key}")
            stored_name = os.path.basename(existing_key)
            catalog_parsed = {**parsed, "file_name": stored_name}
            result["gcs_key"] = existing_key
            result["status"] = "already_in_gcs"
            result["action"] = "skip_exists"
            if bool(bq_cfg.get("enabled", True)) and bool(bq_cfg.get("catalog_existing_in_gcs", True)):
                row = build_catalog_row(
                    parsed=catalog_parsed,
                    gcs_bucket=gcs_bucket,
                    gcs_key=existing_key,
                    s3_bucket=s3_bucket,
                    s3_key=s3_key,
                    file_size_bytes=int(item.get("size") or 0),
                    sync_mode=sync_mode,
                    processed_at=processed_at,
                    convert_method="already_in_gcs",
                    duration_seconds=None,
                    actual_format=None,
                    encoding=None,
                )
                inserted = catalog_files(
                    project_id=gcp_cfg["project_id"],
                    dataset_id=bq_cfg.get("dataset_id", "raw_queue_smart"),
                    table_id=bq_cfg.get("table_id", "hist_queesmart_mp3_catalog"),
                    rows=[row],
                    location=bq_cfg.get("location", "US"),
                )
                result["bq_inserted"] = inserted
            return result

    voice_filter = str(audio_cfg.get("voice_filter") or audio_cfg.get("loudnorm_filter") or DEFAULT_VOICE_FILTER)
    enable_nr = bool(audio_cfg.get("enable_noise_reduction", False))
    noise_filter = str(audio_cfg.get("noise_filter") or DEFAULT_NOISE_FILTER)
    timeout = int(audio_cfg.get("ffmpeg_timeout_seconds", 300))
    chunk = int(audio_cfg.get("io_chunk_size_bytes", 8 * 1024 * 1024))
    audio_filter = build_audio_filter(
        voice_filter=voice_filter,
        enable_noise_reduction=enable_nr,
        noise_filter=noise_filter,
    )

    with tempfile.TemporaryDirectory(prefix="qs_audio_") as tmpdir:
        _, src_ext = os.path.splitext(source_name)
        local_src = os.path.join(tmpdir, f"source{src_ext or '.bin'}")
        local_out = os.path.join(tmpdir, "output.bin")

        print(f"[worker] download s3://{s3_bucket}/{s3_key} → disk (streaming)")
        stream_s3_to_file(
            s3_client,
            bucket=s3_bucket,
            key=s3_key,
            dest_path=local_src,
            chunk_size=chunk,
        )

        probe = probe_media(local_src, timeout=min(60, timeout))
        action = decide_action(probe)
        out_ext = extension_for_action(action, probe, source_name)
        stored_name = storage_file_name(stem, out_ext)
        gcs_key = gcs_key_for_audio(
            stored_name,
            parsed["file_date"],
            gcs_prefix,
            date_folder_format=date_folder_format,
        )
        catalog_parsed = {**parsed, "file_name": stored_name}
        result["gcs_key"] = gcs_key

        print(
            f"[worker] probe format={probe.actual_format} "
            f"duration_s={probe.duration_seconds} → action={action} "
            f"gcs_ext={out_ext}"
        )

        # Por si otro task subió entre el check previo y ahora
        if skip_if_exists and gcs_blob_exists(gcs_client, gcs_bucket, gcs_key):
            print(f"[worker] SKIP already_in_gcs (post-probe) gs://{gcs_bucket}/{gcs_key}")
            result["status"] = "already_in_gcs"
            result["action"] = "skip_exists"
            return result

        if action == "pass_through":
            copy_file(local_src, local_out, chunk_size=chunk)
            content_type = _guess_content_type(probe)
            convert_method = f"passthrough_{probe.actual_format.replace('/', '_')}"
            duration_seconds = probe.duration_seconds
            actual_format = probe.actual_format
            encoding = "passthrough"
        else:
            print(f"[worker] transcode → FLAC filter={audio_filter}")
            meta = transcode_to_flac(
                local_src,
                local_out,
                audio_filter=audio_filter,
                timeout=timeout,
            )
            content_type = str(meta["content_type"])
            convert_method = str(meta["method"])
            duration_seconds = meta.get("duration_seconds")
            actual_format = str(meta.get("actual_format") or "flac")
            encoding = "flac"

        size = stream_file_to_gcs(
            gcs_client,
            local_path=local_out,
            bucket=gcs_bucket,
            blob_name=gcs_key,
            content_type=content_type,
            chunk_size=chunk,
        )
        print(
            f"[worker] OK gs://{gcs_bucket}/{gcs_key} "
            f"bytes={size} method={convert_method} format={actual_format}"
        )

    row = build_catalog_row(
        parsed=catalog_parsed,
        gcs_bucket=gcs_bucket,
        gcs_key=gcs_key,
        s3_bucket=s3_bucket,
        s3_key=s3_key,
        file_size_bytes=size,
        sync_mode=sync_mode,
        processed_at=processed_at,
        convert_method=convert_method,
        duration_seconds=float(duration_seconds) if duration_seconds is not None else None,
        actual_format=actual_format,
        encoding=encoding,
    )
    inserted = 0
    if bool(bq_cfg.get("enabled", True)):
        inserted = catalog_files(
            project_id=gcp_cfg["project_id"],
            dataset_id=bq_cfg.get("dataset_id", "raw_queue_smart"),
            table_id=bq_cfg.get("table_id", "hist_queesmart_mp3_catalog"),
            rows=[row],
            location=bq_cfg.get("location", "US"),
        )

    result.update(
        {
            "status": "ok",
            "action": action,
            "actual_format": actual_format,
            "encoding": encoding,
            "convert_method": convert_method,
            "bytes": size,
            "duration_seconds": duration_seconds,
            "bq_inserted": inserted,
        }
    )
    return result


def _guess_content_type(probe) -> str:
    fmt = probe.format_name or ""
    codec = probe.codec_name or ""
    if "webm" in fmt or "matroska" in fmt:
        return "audio/webm"
    if "ogg" in fmt:
        return "audio/ogg"
    if "flac" in fmt:
        return "audio/flac"
    if "wav" in fmt or "w64" in fmt:
        return "audio/wav"
    if "mp3" in fmt or codec == "mp3":
        return "audio/mpeg"
    return "application/octet-stream"
