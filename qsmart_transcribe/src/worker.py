"""Worker: 1 task = 1 audio del manifiesto → STT → BQ."""

from __future__ import annotations

import json
import os
from typing import Any

from google.cloud import storage

from bq_writer import upsert_transcription
from config_loader import process_date_from_env
from manifest import read_manifest_item, read_manifest_meta
from stt_client import transcribe_gcs_uri


def run_worker(config: dict[str, Any]) -> int:
    task_index = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
    task_count = int(os.environ.get("CLOUD_RUN_TASK_COUNT", "1"))
    process_date = process_date_from_env(config)
    gcp = config["gcp"]
    manifest_prefix = config.get("job", {}).get("manifest_prefix", "state/stt_manifests")

    print(
        f"[worker] task_index={task_index}/{task_count} "
        f"process_date={process_date}"
    )

    gcs = storage.Client(project=gcp.get("project_id"))
    meta = read_manifest_meta(
        gcs,
        bucket=gcp["bucket_name"],
        process_date=process_date,
        manifest_prefix=manifest_prefix,
    )
    manifest_count = int(meta.get("count") or 0)
    if manifest_count == 0:
        print(json.dumps({"role": "worker", "status": "ok", "result": "empty_manifest"}))
        return 0
    if task_index >= manifest_count:
        print(f"[worker] task_index={task_index} >= count={manifest_count} — no-op")
        return 0

    item = read_manifest_item(
        gcs,
        bucket=gcp["bucket_name"],
        process_date=process_date,
        manifest_prefix=manifest_prefix,
        task_index=task_index,
    )
    if item is None:
        print(json.dumps({"role": "worker", "status": "error", "error": "missing_item"}))
        return 1

    gcs_uri = item["gcs_uri"]
    print(f"[worker] STT {gcs_uri}")

    try:
        stt = transcribe_gcs_uri(config, gcs_uri)
        upsert_transcription(config, item=item, stt=stt)
        ok = (stt.get("status") or "").upper() == "OK"
        summary = {
            "role": "worker",
            "status": "ok" if ok else "error",
            "task_index": task_index,
            "gcs_uri": gcs_uri,
            "stt_status": stt.get("status"),
            "has_diarization": bool(stt.get("transcripcion_con_hablantes")),
            "transcript_preview": (stt.get("transcripcion") or "")[:120],
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if ok else 1
    except Exception as exc:  # noqa: BLE001
        msg = f"{gcs_uri}: {type(exc).__name__}: {exc}"
        print(f"[worker] ERROR {msg}")
        try:
            upsert_transcription(
                config,
                item=item,
                stt={
                    "status": f"ERROR: {exc}",
                    "transcripcion": None,
                    "transcripcion_con_hablantes": None,
                    "full_response": {"error": str(exc)},
                },
            )
        except Exception as write_exc:  # noqa: BLE001
            print(f"[worker] no se pudo persistir error: {write_exc}")
        print(json.dumps({"role": "worker", "status": "error", "error": msg}, indent=2))
        return 1
