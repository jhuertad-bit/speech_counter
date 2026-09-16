"""Diarización pyannote + alineación con segmentos Whisper → etiquetas Voz N."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DIARIZATION_MODEL = os.environ.get(
    "PYANNOTE_DIARIZATION_MODEL",
    "pyannote/speaker-diarization-3.1",
).strip()


def resolve_hf_token() -> str | None:
    for key in (
        "HF_TOKEN",
        "HUGGINGFACE_TOKEN",
        "HUGGING_FACE_HUB_TOKEN",
        "PYANNOTE_AUTH_TOKEN",
    ):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return None


def resolve_torch_device() -> tuple[str, str]:
    """
    Returns (device, compute_type_for_whisper).
    Whisper uses compute_type; pyannote uses device only.
    """
    force = os.environ.get("WHISPER_DEVICE", "").strip().lower()
    try:
        import torch

        if force == "cpu":
            return "cpu", "int8"
        if force == "cuda" or (force == "" and torch.cuda.is_available()):
            if torch.cuda.is_available():
                return "cuda", "float16"
    except Exception as exc:  # noqa: BLE001
        logger.warning("torch no disponible para CUDA (%s); CPU/int8", exc)
    return "cpu", "int8"


def load_diarization_pipeline(device: str) -> Any | None:
    """
    Carga pyannote/speaker-diarization-3.1.
    Requiere HF token con acceso al modelo gated.
    """
    token = resolve_hf_token()
    if not token:
        logger.warning(
            "Sin HF_TOKEN/HUGGINGFACE_TOKEN — diarización deshabilitada "
            "(acepta pyannote/speaker-diarization-3.1 en Hugging Face)."
        )
        return None

    try:
        from pyannote.audio import Pipeline
        import torch

        # API reciente: token= ; legacy: use_auth_token=
        try:
            pipeline = Pipeline.from_pretrained(DIARIZATION_MODEL, token=token)
        except TypeError:
            pipeline = Pipeline.from_pretrained(
                DIARIZATION_MODEL, use_auth_token=token
            )

        if device == "cuda":
            pipeline.to(torch.device("cuda"))
        logger.info("PyAnnote diarization listo (%s) device=%s", DIARIZATION_MODEL, device)
        return pipeline
    except Exception as exc:  # noqa: BLE001
        logger.error("No se pudo cargar pyannote: %s", exc, exc_info=True)
        return None


def run_diarization(pipeline: Any, wav_path: str) -> list[tuple[float, float, str]]:
    """
    Ejecuta diarización.
    Returns list of (start, end, SPEAKER_XX) sorted by start.
    """
    try:
        # pyannote 3.x: pipeline(file) o pipeline({"audio": path})
        try:
            annotation = pipeline(wav_path)
        except Exception:
            annotation = pipeline({"audio": wav_path})

        # Algunas versiones envuelven (diarization, embeddings)
        if isinstance(annotation, tuple):
            annotation = annotation[0]

        turns: list[tuple[float, float, str]] = []
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            start = float(turn.start)
            end = float(turn.end)
            if end <= start:
                continue
            turns.append((start, end, str(speaker)))
        turns.sort(key=lambda t: (t[0], t[1]))
        return turns
    except Exception as exc:  # noqa: BLE001
        logger.error("Diarización falló para %s: %s", wav_path, exc, exc_info=True)
        return []


def map_speakers_by_first_appearance(
    turns: list[tuple[float, float, str]],
) -> dict[str, str]:
    """SPEAKER_00 → Voz 1, etc. ordenados por primera aparición."""
    mapping: dict[str, str] = {}
    next_idx = 1
    for _start, _end, spk in turns:
        if spk not in mapping:
            mapping[spk] = f"Voz {next_idx}"
            next_idx += 1
    return mapping


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def assign_speaker_to_segment(
    seg_start: float,
    seg_end: float,
    turns: list[tuple[float, float, str]],
    speaker_map: dict[str, str],
) -> str | None:
    """Hablante con mayor solapamiento temporal; None si no hay overlap."""
    if seg_end <= seg_start or not turns:
        return None
    best_spk: str | None = None
    best_ov = 0.0
    for t0, t1, spk in turns:
        ov = _overlap(seg_start, seg_end, t0, t1)
        if ov > best_ov:
            best_ov = ov
            best_spk = spk
    if best_spk is None or best_ov <= 0.0:
        return None
    return speaker_map.get(best_spk, best_spk)


def annotate_whisper_segments(
    whisper_segments: list[Any],
    turns: list[tuple[float, float, str]],
) -> list[dict[str, Any]]:
    """
    Cada segmento Whisper → {start, end, text, speaker}.
    speaker es 'Voz N' o None.
    """
    speaker_map = map_speakers_by_first_appearance(turns)
    annotated: list[dict[str, Any]] = []
    for seg in whisper_segments:
        text = (getattr(seg, "text", None) or "").strip()
        if not text:
            continue
        start = float(getattr(seg, "start", 0.0) or 0.0)
        end = float(getattr(seg, "end", start) or start)
        speaker = assign_speaker_to_segment(start, end, turns, speaker_map)
        annotated.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "speaker": speaker,
            }
        )
    return annotated


def seconds_to_hms(seconds: float) -> str:
    total = max(0, int(seconds))
    hh, rem = divmod(total, 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def seconds_to_mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    mm, ss = divmod(total, 60)
    return f"{mm:02d}:{ss:02d}"


def build_diarized_transcript(
    annotated: list[dict[str, Any]],
    *,
    stamp_format: str = "hms",
    pause_gap_sec: float = 0.8,
) -> str:
    """
    Formato:
      [00:00:01] Voz 1: Hola
      [00:00:03] Voz 2: Todo bien
    Agrupa segmentos consecutivos del mismo hablante si el gap es pequeño.
    """
    if not annotated:
        return ""

    stamp_fn = seconds_to_hms if stamp_format == "hms" else seconds_to_mmss
    lines: list[str] = []
    buf_words: list[str] = []
    buf_speaker: str | None = None
    buf_start: float = float(annotated[0]["start"])
    prev_end: float = float(annotated[0]["start"])

    def flush() -> None:
        nonlocal buf_words, buf_speaker
        if not buf_words:
            return
        stamp = stamp_fn(buf_start)
        label = buf_speaker or "Voz ?"
        lines.append(f"[{stamp}] {label}: {' '.join(buf_words).strip()}")
        buf_words = []

    for item in annotated:
        text = item["text"]
        spk = item.get("speaker")
        start = float(item["start"])
        end = float(item["end"])
        gap = start - prev_end
        speaker_changed = buf_words and spk != buf_speaker
        pause_break = buf_words and gap >= pause_gap_sec and spk == buf_speaker

        if speaker_changed or pause_break:
            flush()
            buf_start = start
            buf_speaker = spk
        if not buf_words:
            buf_start = start
            buf_speaker = spk
        buf_words.append(text)
        prev_end = end

    flush()
    return "\n".join(lines)
