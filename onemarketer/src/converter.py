"""
Detección y conversión de audio hacia MP3 vía ffmpeg/pydub.

Incluye contenedores de video con pista de audio (p. ej. video/mpeg, .mpg de WhatsApp).
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
    ".mpeg": "mpeg",
    ".mpg": "mpeg",
    ".mpe": "mpeg",
    ".m2v": "mpeg",
    ".mov": "mov",
    ".qt": "mov",
    ".avi": "avi",
    ".mkv": "matroska",
    ".m4v": "mp4",
    ".wmv": "wmv",
    ".asf": "wmv",
    ".flv": "flv",
    ".f4v": "flv",
    ".ts": "mpegts",
    ".m2ts": "mpegts",
    ".mts": "mpegts",
    ".vob": "mpeg",
}

# Contenedores de video (MPEG, MOV, etc.) con pista de audio — común en notas de voz WhatsApp
VIDEO_AUDIO_EXTENSIONS: frozenset[str] = frozenset({
    ".mpeg", ".mpg", ".mpe", ".m2v", ".mov", ".qt", ".avi", ".mkv", ".m4v",
    ".wmv", ".asf", ".flv", ".f4v", ".ts", ".m2ts", ".mts", ".vob",
})


def normalize_extension(file_name: str) -> str:
    _, ext = os.path.splitext(file_name.lower())
    return ext


def is_video_audio_container(file_name: str) -> bool:
    return normalize_extension(file_name) in VIDEO_AUDIO_EXTENSIONS


def is_supported_audio(
    file_name: str,
    supported_extensions: list[str],
    *,
    include_video_containers: bool = True,
) -> bool:
    ext = normalize_extension(file_name)
    normalized = [e.lower() if e.startswith(".") else f".{e.lower()}" for e in supported_extensions]
    if ext in normalized:
        return True
    if include_video_containers and ext in VIDEO_AUDIO_EXTENSIONS:
        return True
    return False


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


def _bitrate_bps_to_kbps(raw: str | None) -> str | None:
    if not raw:
        return None
    value = raw.strip().upper()
    if value in {"", "N/A", "NA", "UNKNOWN"}:
        return None
    try:
        bitrate_bps = int(float(value))
    except ValueError:
        return None
    if bitrate_bps <= 0:
        return None
    return f"{max(64, int(bitrate_bps / 1000))}k"


def _ffprobe_bitrate_field(file_path: str, show_entries: str) -> str | None:
    cmd = ["ffprobe", "-v", "error"]
    if show_entries.startswith("stream="):
        cmd.extend(["-select_streams", "a:0"])
    cmd.extend([
        "-show_entries",
        show_entries,
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        file_path,
    ])
    result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=60)
    return _bitrate_bps_to_kbps(result.stdout)


def get_audio_bitrate(file_path: str) -> str | None:
    for show_entries in ("stream=bit_rate", "format=bit_rate"):
        try:
            kbps = _ffprobe_bitrate_field(file_path, show_entries)
            if kbps:
                return kbps
        except Exception as exc:  # noqa: BLE001
            logger.debug("ffprobe %s for %s: %s", show_entries, file_path, exc)
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
    include_video = audio_cfg.get("include_video_containers", True)
    supported = audio_cfg.get("supported_extensions", [])
    default_bitrate = audio_cfg.get("default_bitrate", "128k")
    timeout = int(audio_cfg.get("ffmpeg_timeout_seconds", 300))
    min_duration = float(audio_cfg.get("min_duration_seconds", 0.1))

    if not is_supported_audio(file_name, supported, include_video_containers=include_video):
        raise ValueError(f"Extensión no soportada: {file_name}")

    probe = probe_audio(input_path)
    if probe is None:
        raise ValueError(f"Sin pista de audio válida (puede ser video sin audio): {file_name}")

    if probe["duration"] < min_duration:
        raise ValueError(f"Audio duration below minimum ({probe['duration']}s)")

    bitrate = get_audio_bitrate(input_path) or default_bitrate
    method = "ffmpeg"
    video_container = is_video_audio_container(file_name)

    # Contenedores MPEG/video: ffmpeg -vn extrae solo audio (pydub suele fallar)
    if video_container:
        convert_with_ffmpeg(input_path, output_path, bitrate, timeout=timeout)
    else:
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
