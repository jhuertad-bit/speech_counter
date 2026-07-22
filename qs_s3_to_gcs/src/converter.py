"""Detección de formato (ffprobe) y transcodificación condicional → FLAC o pass-through.

Speech-to-Text v2 (Chirp) soporta nativamente: webm/opus, ogg/opus, flac, wav, mp3.
Si el contenedor ya es compatible → pass-through (sin re-encode).
Si no → FLAC + loudnorm + banda telefónica (sin pérdida, mejor para STT que MP3).

Importante: el prefijo GCS / nombres de tablas pueden seguir diciendo "mp3"
(etiquetas heredadas). El objeto en GCS usa la extensión real (.webm, .flac, …).
El formato también se reporta en actual_format / encoding / convert_method.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any

SUPPORTED_EXTENSIONS = frozenset({
    ".mp3", ".webm", ".ogg", ".opus", ".wav", ".wave", ".flac",
    ".m4a", ".aac", ".wma", ".amr", ".3gp", ".mp4", ".aiff", ".aif",
    ".caf", ".mp2", ".mpeg", ".mpg",
})

# Extensiones posibles ya existentes en GCS (legacy .mp3 + formatos reales).
KNOWN_STORAGE_EXTS = (".webm", ".ogg", ".opus", ".flac", ".wav", ".mp3", ".m4a")

# Loudnorm EBU R128 + banda voz telefónica (requisito STT / call center).
DEFAULT_VOICE_FILTER = "highpass=f=200,lowpass=f=3400,loudnorm=I=-16:TP=-1.5:LRA=11"
DEFAULT_NOISE_FILTER = "afftdn"

# Contenedores/codecs que Chirp/STT suelen aceptar sin re-encode.
_STT_NATIVE: tuple[tuple[str, ...], tuple[str, ...]] = (
    # (format_name substrings), (codec_name substrings) — codec vacío = cualquier
    (("webm", "matroska"), ("opus",)),
    (("ogg",), ("opus",)),
    (("flac",), ()),
    (("wav", "w64"), ()),
    (("mp3",), ()),
)


@dataclass(frozen=True)
class ProbeInfo:
    format_name: str
    codec_name: str
    duration_seconds: float | None
    sample_rate: int | None
    channels: int | None

    @property
    def actual_format(self) -> str:
        fmt = (self.format_name or "unknown").split(",")[0].strip().lower()
        codec = (self.codec_name or "").strip().lower()
        if codec:
            return f"{fmt}/{codec}"
        return fmt or "unknown"


def normalize_extension(file_name: str) -> str:
    _, ext = os.path.splitext(file_name.lower())
    return ext


def is_supported_audio(file_name: str) -> bool:
    return normalize_extension(file_name) in SUPPORTED_EXTENSIONS


def mp3_file_name(source_file_name: str) -> str:
    """Compat: stem.mp3 (legado). Preferir storage_file_name() para objetos nuevos."""
    stem, _ = os.path.splitext(source_file_name)
    return f"{stem}.mp3"


def file_stem(source_file_name: str) -> str:
    stem, _ = os.path.splitext(source_file_name)
    return stem


def storage_file_name(stem: str, extension: str) -> str:
    """Nombre del objeto en GCS con extensión real (.webm, .flac, …)."""
    ext = extension if extension.startswith(".") else f".{extension}"
    return f"{stem}{ext.lower()}"


def extension_for_action(action: str, probe: ProbeInfo, source_file_name: str) -> str:
    """Extensión del blob según pass-through vs FLAC."""
    if action == "transcode_flac":
        return ".flac"
    # pass-through: preferir extensión del archivo origen si es conocida
    _, src_ext = os.path.splitext(source_file_name.lower())
    if src_ext in SUPPORTED_EXTENSIONS:
        if src_ext == ".wave":
            return ".wav"
        return src_ext
    return extension_from_probe(probe)


def extension_from_probe(probe: ProbeInfo) -> str:
    fmt = probe.format_name or ""
    codec = probe.codec_name or ""
    if "webm" in fmt or "matroska" in fmt:
        return ".webm"
    if "ogg" in fmt:
        return ".ogg"
    if "flac" in fmt:
        return ".flac"
    if "wav" in fmt or "w64" in fmt:
        return ".wav"
    if "mp3" in fmt or codec == "mp3":
        return ".mp3"
    if "opus" in codec:
        return ".ogg"
    return ".bin"


def probe_media(audio_path: str, *, timeout: int = 60) -> ProbeInfo:
    """ffprobe del archivo real (no confiar en la extensión)."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=format_name,duration:stream=codec_name,codec_type,sample_rate,channels",
        "-of",
        "json",
        audio_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "ffprobe failed")

    payload = json.loads(result.stdout or "{}")
    fmt = str((payload.get("format") or {}).get("format_name") or "").lower()
    duration_raw = (payload.get("format") or {}).get("duration")
    duration: float | None
    try:
        duration = float(duration_raw) if duration_raw is not None else None
        if duration is not None and duration < 0:
            duration = None
    except (TypeError, ValueError):
        duration = None

    codec = ""
    sample_rate: int | None = None
    channels: int | None = None
    for stream in payload.get("streams") or []:
        if str(stream.get("codec_type") or "").lower() != "audio":
            continue
        codec = str(stream.get("codec_name") or "").lower()
        try:
            sample_rate = int(stream["sample_rate"]) if stream.get("sample_rate") else None
        except (TypeError, ValueError):
            sample_rate = None
        try:
            channels = int(stream["channels"]) if stream.get("channels") is not None else None
        except (TypeError, ValueError):
            channels = None
        break

    return ProbeInfo(
        format_name=fmt,
        codec_name=codec,
        duration_seconds=duration,
        sample_rate=sample_rate,
        channels=channels,
    )


def probe_duration_seconds(audio_path: str, *, timeout: int = 60) -> float | None:
    try:
        return probe_media(audio_path, timeout=timeout).duration_seconds
    except Exception:  # noqa: BLE001
        return None


def is_stt_native(probe: ProbeInfo) -> bool:
    fmt = probe.format_name or ""
    codec = probe.codec_name or ""
    for fmt_keys, codec_keys in _STT_NATIVE:
        if not any(k in fmt for k in fmt_keys):
            continue
        if not codec_keys:
            return True
        if any(k in codec for k in codec_keys):
            return True
    return False


def build_audio_filter(
    *,
    voice_filter: str = DEFAULT_VOICE_FILTER,
    enable_noise_reduction: bool = False,
    noise_filter: str = DEFAULT_NOISE_FILTER,
) -> str:
    parts = [voice_filter.strip()] if voice_filter.strip() else []
    if enable_noise_reduction and noise_filter.strip():
        parts.insert(0, noise_filter.strip())
    return ",".join(parts)


def transcode_to_flac(
    input_path: str,
    output_path: str,
    *,
    audio_filter: str = DEFAULT_VOICE_FILTER,
    timeout: int = 300,
) -> dict[str, Any]:
    """Re-encode a FLAC (sin pérdida) con filtros de voz/loudnorm."""
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
        audio_filter,
        "-c:a",
        "flac",
        "-y",
        output_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or "ffmpeg flac conversion failed")
    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("FLAC output is empty")

    out_probe = probe_media(output_path, timeout=min(60, timeout))
    return {
        "method": "ffmpeg_flac_loudnorm",
        "audio_filter": audio_filter,
        "output_size_bytes": os.path.getsize(output_path),
        "duration_seconds": out_probe.duration_seconds,
        "actual_format": out_probe.actual_format,
        "content_type": "audio/flac",
    }


def decide_action(probe: ProbeInfo) -> str:
    """pass_through | transcode_flac"""
    return "pass_through" if is_stt_native(probe) else "transcode_flac"
