"""
Detección y conversión de cualquier formato de audio soportado por ffmpeg hacia MP3.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError

logger = logging.getLogger(__name__)

AudioSegment.converter = "ffmpeg"
AudioSegment.ffmpeg = "ffmpeg"
AudioSegment.ffprobe = "ffprobe"

# Mapeo extensión -> hint para pydub (ffmpeg detecta igual sin esto)
PYDUB_FORMAT_HINTS: dict[str, str] = {
    ".ogg": "ogg",
    ".opus": "ogg",
    ".wav": "wav",
    ".wave": "wav",
    ".flac": "flac",
    ".m4a": "mp4",
    ".mp4": "mp4",
    ".aac": "aac",
    ".wma": "wma",
    ".amr": "amr",
    ".3gp": "mp4",
    ".webm": "webm",
    ".aiff": "aiff",
    ".aif": "aiff",
    ".caf": "caf",
    ".mp2": "mp2",
}


def normalize_extension(file_name: str) -> str:
    _, ext = os.path.splitext(file_name.lower())
    return ext


def is_supported_audio(file_name: str, supported_extensions: list[str]) -> bool:
    ext = normalize_extension(file_name)
    normalized = [e.lower() if e.startswith(".") else f".{e.lower()}" for e in supported_extensions]
    return ext in normalized


def probe_audio(file_path: str) -> dict[str, Any] | None:
    """Valida con ffprobe que el archivo tenga al menos un stream de audio."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,codec_type:format=format_name,duration",
        "-of",
        "json",
        file_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            return None
        fmt = data.get("format") or {}
        return {
            "codec": streams[0].get("codec_name"),
            "format": fmt.get("format_name"),
            "duration": float(fmt.get("duration") or streams[0].get("duration") or 0),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("ffprobe failed for %s: %s", file_path, exc)
        return None


def get_audio_bitrate(file_path: str) -> str | None:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=bit_rate",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        file_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
        bitrate_bps = int(result.stdout.strip())
        return f"{max(64, int(bitrate_bps / 1000))}k"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not detect bitrate for %s: %s", file_path, exc)
        return None


def convert_with_ffmpeg(
    input_path: str,
    output_path: str,
    bitrate: str,
    timeout: int = 300,
) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-err_detect",
        "ignore_err",
        "-i",
        input_path,
        "-vn",
        "-map_metadata",
        "0",
        "-c:a",
        "libmp3lame",
        "-b:a",
        bitrate,
        "-y",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "ffmpeg conversion failed")
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("MP3 output is empty")


def convert_with_pydub(
    input_path: str,
    output_path: str,
    bitrate: str,
    extension: str,
) -> None:
    fmt = PYDUB_FORMAT_HINTS.get(extension)
    if fmt:
        audio = AudioSegment.from_file(input_path, format=fmt)
    else:
        audio = AudioSegment.from_file(input_path)

    if audio.duration_seconds < 0.1:
        raise ValueError(f"Audio too short ({audio.duration_seconds}s)")

    audio.export(output_path, format="mp3", bitrate=bitrate)


def convert_audio_to_mp3(
    input_path: str,
    output_path: str,
    file_name: str,
    audio_cfg: dict[str, Any],
) -> dict[str, Any]:
    """
    Convierte un archivo de audio a MP3.
    Retorna metadata de la conversión.
    """
    extension = normalize_extension(file_name)
    default_bitrate = audio_cfg.get("default_bitrate", "128k")
    timeout = int(audio_cfg.get("ffmpeg_timeout_seconds", 300))
    min_duration = float(audio_cfg.get("min_duration_seconds", 0.1))

    probe = probe_audio(input_path)
    if probe is None:
        raise ValueError(f"File is not a valid audio stream: {file_name}")

    if probe["duration"] < min_duration:
        raise ValueError(f"Audio duration below minimum ({probe['duration']}s)")

    bitrate = get_audio_bitrate(input_path) or default_bitrate
    method = "ffmpeg"

    try:
        convert_with_pydub(input_path, output_path, bitrate, extension)
        method = "pydub"
    except (CouldntDecodeError, Exception) as pydub_error:
        logger.warning("pydub failed (%s), using ffmpeg", pydub_error)
        if os.path.exists(output_path):
            os.remove(output_path)
        convert_with_ffmpeg(input_path, output_path, bitrate, timeout=timeout)
        method = "ffmpeg"

    return {
        "method": method,
        "bitrate": bitrate,
        "source_codec": probe.get("codec"),
        "source_format": probe.get("format"),
        "duration_seconds": probe.get("duration"),
        "source_extension": extension,
    }
