"""Probe de metadata de audio con ffprobe (sin conversión)."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.cloud import storage


@dataclass(frozen=True)
class AudioProbe:
    duration_seconds: float | None
    audio_codec: str | None
    sample_rate_hz: int | None
    channels: int | None
    format_name: str | None
    bit_rate: int | None


def probe_local_file(audio_path: str, *, timeout: int = 60) -> AudioProbe:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=format_name,duration,bit_rate:stream=codec_name,codec_type,sample_rate,channels",
        "-of",
        "json",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "ffprobe failed")

    payload = json.loads(result.stdout or "{}")
    fmt_obj = payload.get("format") or {}
    fmt = str(fmt_obj.get("format_name") or "").lower() or None

    duration: float | None
    try:
        duration = float(fmt_obj["duration"]) if fmt_obj.get("duration") is not None else None
        if duration is not None and duration < 0:
            duration = None
    except (TypeError, ValueError):
        duration = None

    bit_rate: int | None
    try:
        bit_rate = int(fmt_obj["bit_rate"]) if fmt_obj.get("bit_rate") else None
    except (TypeError, ValueError):
        bit_rate = None

    codec: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    for stream in payload.get("streams") or []:
        if str(stream.get("codec_type") or "").lower() != "audio":
            continue
        codec = str(stream.get("codec_name") or "").lower() or None
        try:
            sample_rate = int(stream["sample_rate"]) if stream.get("sample_rate") else None
        except (TypeError, ValueError):
            sample_rate = None
        try:
            channels = int(stream["channels"]) if stream.get("channels") is not None else None
        except (TypeError, ValueError):
            channels = None
        break

    return AudioProbe(
        duration_seconds=duration,
        audio_codec=codec,
        sample_rate_hz=sample_rate,
        channels=channels,
        format_name=fmt,
        bit_rate=bit_rate,
    )


def probe_gcs_blob(
    client: storage.Client,
    bucket: str,
    object_name: str,
    *,
    timeout: int = 60,
) -> AudioProbe:
    """Descarga a temp, ffprobe, borra. Solo metadata."""
    suffix = Path(object_name).suffix or ".m4a"
    blob = client.bucket(bucket).blob(object_name)
    with tempfile.NamedTemporaryFile(prefix="mentores_probe_", suffix=suffix, delete=True) as tmp:
        blob.download_to_filename(tmp.name)
        return probe_local_file(tmp.name, timeout=timeout)


def probe_to_dict(probe: AudioProbe | None) -> dict[str, Any]:
    if probe is None:
        return {
            "duration_seconds": None,
            "audio_codec": None,
            "sample_rate_hz": None,
            "channels": None,
            "format_name": None,
            "bit_rate": None,
        }
    return {
        "duration_seconds": probe.duration_seconds,
        "audio_codec": probe.audio_codec,
        "sample_rate_hz": probe.sample_rate_hz,
        "channels": probe.channels,
        "format_name": probe.format_name,
        "bit_rate": probe.bit_rate,
    }
