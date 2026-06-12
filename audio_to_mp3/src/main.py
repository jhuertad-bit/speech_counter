"""
Cloud Function: convierte cualquier formato de audio soportado a MP3 al subirse a GCS.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

import functions_framework
from google.cloud import storage

from converter import convert_audio_to_mp3, is_supported_audio, normalize_extension
from gcp_runtime_log import (
    AUDIO_MP3_ENV,
    AUDIO_MP3_REQUIRED,
    finalize_gcp_config,
    get_runtime_service_account_email,
    print_runtime_gcp_info,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


_runtime_logged = False


def load_config() -> dict:
    config_path = os.environ.get("CONFIG_PATH", "config/config.json")
    if not os.path.exists(config_path):
        config_path = os.path.join(os.path.dirname(__file__), config_path)
    if not os.path.exists(config_path):
        config_path = os.path.join(os.path.dirname(__file__), "config", "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    logger.info("[audio-to-mp3] Config desde %s", config_path)
    return finalize_gcp_config(
        config, AUDIO_MP3_ENV, AUDIO_MP3_REQUIRED, service_label="audio-to-mp3"
    )


def build_destination_path(
    file_path: str,
    input_base: str,
    mp3_base: str,
    source_ext: str,
) -> str:
    if input_base in file_path:
        destination = file_path.replace(input_base, mp3_base, 1)
    else:
        destination = file_path

    for ext in (source_ext, ".opus", ".wave", ".aif"):
        if destination.lower().endswith(ext):
            return destination[: -len(ext)] + ".mp3"

    base, _ = os.path.splitext(destination)
    return base + ".mp3"


def validate_input_path(file_path: str, path_audios_input: str) -> bool:
    input_base = path_audios_input.split("/fecha_descarga=")[0]
    file_dir = "/".join(file_path.split("/")[:-1])
    return input_base in file_dir


@functions_framework.cloud_event
def audio_to_mp3_converter(cloud_event):
    global _runtime_logged
    config = load_config()
    gcp = config["gcp"]
    audio_cfg = config.get("audio", {})

    if not _runtime_logged:
        _runtime_logged = True
        print_runtime_gcp_info(
            config,
            service_label="audio-to-mp3",
            config_sa_field="service_account_email",
            extra_lines=[
                f"Input prefix:  {gcp.get('path_audios_input', '')}",
                f"Output prefix: {gcp.get('path_audios_mp3', '')}",
            ],
        )
        logger.info(
            "[audio-to-mp3] SA runtime=%s | trigger bucket event",
            get_runtime_service_account_email(),
        )

    data = cloud_event.data
    bucket_name = data["bucket"]
    file_path = data["name"]

    logger.info(
        "[audio-to-mp3] Processing %s | bucket=%s | SA=%s",
        file_path, bucket_name, get_runtime_service_account_email(),
    )

    if not validate_input_path(file_path, gcp["path_audios_input"]):
        logger.info("Path not in configured input prefix, skipping: %s", file_path)
        return

    supported = audio_cfg.get("supported_extensions", [])
    include_video = audio_cfg.get("include_video_containers", True)
    if not is_supported_audio(
        os.path.basename(file_path), supported, include_video_containers=include_video
    ):
        logger.info("Extension not supported, skipping: %s", file_path)
        return

    ext = normalize_extension(os.path.basename(file_path))
    if ext == ".mp3":
        logger.info("Already MP3, skipping: %s", file_path)
        return

    input_base = gcp["path_audios_input"].split("/fecha_descarga=")[0]
    mp3_base = gcp["path_audios_mp3"].split("/fecha_descarga=")[0]
    destination_path = build_destination_path(file_path, input_base, mp3_base, ext)

    timeout = 300
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    if audio_cfg.get("skip_existing_mp3", True):
        dest_blob = bucket.blob(destination_path)
        if dest_blob.exists():
            logger.info("MP3 already exists, skipping: %s", destination_path)
            return

    file_name = os.path.basename(file_path)
    base_name = os.path.splitext(file_name)[0]
    temp_dir = tempfile.gettempdir()
    temp_input = os.path.join(temp_dir, file_name)
    temp_mp3 = os.path.join(temp_dir, f"{base_name}.mp3")

    try:
        logger.info("Downloading %s", file_path)
        bucket.blob(file_path).download_to_filename(temp_input, timeout=timeout)

        meta = convert_audio_to_mp3(temp_input, temp_mp3, file_name, audio_cfg)
        logger.info(
            "Converted %s -> MP3 via %s (codec=%s, bitrate=%s)",
            ext,
            meta["method"],
            meta.get("source_codec"),
            meta["bitrate"],
        )

        logger.info("Uploading to %s", destination_path)
        dest = bucket.blob(destination_path)
        dest.upload_from_filename(temp_mp3, timeout=timeout, content_type="audio/mpeg")
        dest.metadata = {
            "source_format": meta.get("source_format") or "",
            "source_codec": meta.get("source_codec") or "",
            "conversion_method": meta.get("method") or "",
        }
        dest.patch()

        logger.info("Done: %s", destination_path)

    except Exception as exc:
        logger.error("Error processing %s: %s", file_path, exc)
        raise

    finally:
        for path in (temp_input, temp_mp3):
            if os.path.exists(path):
                os.remove(path)
