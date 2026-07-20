"""Conversión a MP3 con loudnorm (EBU R128) vía ffmpeg."""

from __future__ import annotations

import os
import subprocess
from typing import Any

SUPPORTED_EXTENSIONS = frozenset({
    ".mp3", ".webm", ".ogg", ".opus", ".wav", ".wave", ".flac",
    ".m4a", ".aac", ".wma", ".amr", ".3gp", ".mp4", ".aiff", ".aif",
    ".caf", ".mp2", ".mpeg", ".mpg",
})

DEFAULT_LOUDNORM = "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11"


def normalize_extension(file_name: str) -> str:
    _, ext = os.path.splitext(file_name.lower())
    return ext


def is_supported_audio(file_name: str) -> bool:
    return normalize_extension(file_name) in SUPPORTED_EXTENSIONS


def mp3_file_name(source_file_name: str) -> str:
    stem, _ = os.path.splitext(source_file_name)
    return f"{stem}.mp3"


def convert_audio_to_mp3(
    input_path: str,
    output_path: str,
    *,
    bitrate: str = "128k",
    loudnorm_filter: str = DEFAULT_LOUDNORM,
    timeout: int = 300,
) -> dict[str, Any]:
    """
    Convierte cualquier audio soportado a MP3 y normaliza volumen con loudnorm.
    """
    if not os.path.exists(input_path) or os.path.getsize(input_path) == 0:
        raise ValueError(f"Input vacío o inexistente: {input_path}")

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
        "-af",
        loudnorm_filter,
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

    return {
        "method": "ffmpeg_loudnorm",
        "bitrate": bitrate,
        "loudnorm_filter": loudnorm_filter,
        "output_size_bytes": os.path.getsize(output_path),
    }
