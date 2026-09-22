"""
cr_serialize_cita/main.py
Cloud Run Job — Whisper LOCAL para Cita Promotor y Mentores.

Lee gcs_uri desde hist_cita_*_audio_catalog (fecha_audio).
Escribe hist_cita_*_audio_whisper_raw / _prd (transcripcion [MM:SS]).

Canal: CITA_CANAL=promotor|mentor (env) o config.json.
Modos: FECHA_AUDIO=YYYY-MM-DD | GCS_URIS=gs://a,gs://b
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from faster_whisper import WhisperModel
from google.cloud import bigquery, storage
from pydub import AudioSegment

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

CONFIG_PATH = os.environ.get(
    "CONFIG_PATH",
    str(Path(__file__).resolve().parent / "config" / "config.json"),
)
with open(CONFIG_PATH, encoding="utf-8") as f:
    CONFIG = json.load(f)

GCP = dict(CONFIG["gcp"])
CANALES = dict(CONFIG["canales"])

CITA_CANAL = os.environ.get("CITA_CANAL", "promotor").strip().lower() or "promotor"
if CITA_CANAL not in CANALES:
    raise ValueError(f"CITA_CANAL inválido: {CITA_CANAL!r} (promotor|mentor)")

CANAL = dict(CANALES[CITA_CANAL])

if os.environ.get("GCP_PROJECT_ID"):
    GCP["project_id"] = os.environ["GCP_PROJECT_ID"].strip()
if os.environ.get("GCP_BUCKET_AUDIO"):
    CANAL["bucket_audio"] = os.environ["GCP_BUCKET_AUDIO"].strip()
if os.environ.get("CITA_DATASET"):
    GCP["dataset"] = os.environ["CITA_DATASET"].strip()
if os.environ.get("CITA_TABLE_CATALOG"):
    CANAL["table_catalog"] = os.environ["CITA_TABLE_CATALOG"].strip()
if os.environ.get("CITA_TABLE_WHISPER_RAW"):
    CANAL["table_whisper_raw"] = os.environ["CITA_TABLE_WHISPER_RAW"].strip()
if os.environ.get("CITA_TABLE_WHISPER_PRD"):
    CANAL["table_whisper_prd"] = os.environ["CITA_TABLE_WHISPER_PRD"].strip()

PROJECT = GCP["project_id"]
DATASET = GCP["dataset"]
TABLE_CATALOG = f"{PROJECT}.{DATASET}.{CANAL['table_catalog']}"
TABLE_RAW = f"{PROJECT}.{DATASET}.{CANAL['table_whisper_raw']}"
TABLE_PRD = f"{PROJECT}.{DATASET}.{CANAL['table_whisper_prd']}"

FECHA_AUDIO = os.environ.get("FECHA_AUDIO", "").strip()
GCS_URIS = os.environ.get("GCS_URIS", "").strip()
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "turbo").strip() or "turbo"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


WHISPER_BEAM_SIZE = max(1, _env_int("WHISPER_BEAM_SIZE", 1))
WHISPER_WORD_TIMESTAMPS = _env_bool("WHISPER_WORD_TIMESTAMPS", False)
WHISPER_CONDITION_ON_PREVIOUS = _env_bool("WHISPER_CONDITION_ON_PREVIOUS", False)
WHISPER_CPU_THREADS = max(1, _env_int("WHISPER_CPU_THREADS", 0) or (os.cpu_count() or 4))
WHISPER_NUM_WORKERS = max(1, _env_int("WHISPER_NUM_WORKERS", 1))
WHISPER_DOWNLOAD_ROOT = (
    os.environ.get("WHISPER_DOWNLOAD_ROOT", "").strip() or "/app/models"
)
WHISPER_FORCE_MONO_WAV = _env_bool("WHISPER_FORCE_MONO_WAV", False)
_DIRECT_AUDIO_SUFFIXES = {".flac", ".wav", ".mp3", ".m4a", ".ogg", ".opus", ".webm"}

_PROMPTS = {
    "promotor": (
        "Conversación telefónica o presencial de cita con un promotor de la "
        "Universidad Tecnológica del Perú (UTP), en español de Perú "
        "(costa, sierra y selva). Vocabulario: matrícula, pensión, carrera, "
        "campus, examen de admisión, descuento, vacante, DNI, Pronabec. "
        "No inventar palabras en inglés."
    ),
    "mentor": (
        "Conversación de mentoría académica UTP en español de Perú "
        "(costa, sierra y selva). Hablan mentor y estudiante o apoderado. "
        "Vocabulario: cursos, notas, tutoría, malla, ciclo, campus, DNI. "
        "No inventar palabras en inglés."
    ),
}
WHISPER_INITIAL_PROMPT = (
    os.environ.get("WHISPER_INITIAL_PROMPT", "").strip()
    or _PROMPTS.get(CITA_CANAL, _PROMPTS["promotor"])
)

PAUSE_GAP_SEC = 0.8
NO_SPEECH_PROB_THRESHOLD = 0.60
HALLUCINATION_PHRASES = {
    "gracias por ver el video",
    "gracias por ver el video.",
    "subtítulos por la comunidad de amara.org",
    "suscríbete al canal",
    "suscríbete al canal.",
}

MODEL_MAP = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large": "Systran/faster-whisper-large-v3",
    "large-v3": "Systran/faster-whisper-large-v3",
    "turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
}

logger.info(
    "Cita Whisper canal=%s catalog=%s raw=%s prd=%s",
    CITA_CANAL,
    TABLE_CATALOG,
    TABLE_RAW,
    TABLE_PRD,
)

# ---------------------------------------------------------------------------
# Anti-loop (conservador para evaluación)
# ---------------------------------------------------------------------------
_MAX_PHRASE_LEN = 8
_COLLAPSE_MIN_REPS = 4
_COLLAPSE_MAX_KEEP = 2
_SHORT_TOKEN_MIN_REPS = 6


def _norm_token(w: str) -> str:
    return re.sub(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]+", "", w, flags=re.UNICODE).lower()


def _min_reps_for_phrase(phrase: list[str]) -> int:
    if len(phrase) == 1 and len(_norm_token(phrase[0])) <= 4:
        return _SHORT_TOKEN_MIN_REPS
    return _COLLAPSE_MIN_REPS


def _collapse_word_runs(words: list[str], *, max_keep: int) -> list[str]:
    n = len(words)
    out: list[str] = []
    i = 0
    while i < n:
        max_len = min(_MAX_PHRASE_LEN, (n - i) // 3)
        best: tuple[int, int, int, list[str]] | None = None
        for length in range(1, max_len + 1):
            phrase = words[i : i + length]
            phrase_norm = [_norm_token(w) for w in phrase]
            if not any(phrase_norm):
                continue
            need = _min_reps_for_phrase(phrase)
            reps = 1
            j = i + length
            while j + length <= n:
                nxt = [_norm_token(w) for w in words[j : j + length]]
                if nxt != phrase_norm:
                    break
                reps += 1
                j += length
            if reps >= need:
                cand = (reps, -length, j, phrase)
                if best is None or cand[:2] > best[:2]:
                    best = cand
        if best is not None:
            _reps, _neg, j, phrase = best
            for _ in range(min(_reps, max_keep)):
                out.extend(phrase)
            i = j
        else:
            out.append(words[i])
            i += 1
    return out


def collapse_repetitions(text: str, *, max_keep: int = _COLLAPSE_MAX_KEEP) -> str:
    if not text or not text.strip():
        return text
    words = text.split()
    if len(words) >= 4:
        text = " ".join(_collapse_word_runs(words, max_keep=max_keep))
    text = re.sub(
        r"\b([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]{1,24})(?:\s*([-/_,.])\s*\1){2,}\b",
        lambda m: (m.group(1) + m.group(2)) * (max_keep - 1) + m.group(1),
        text,
    )
    return re.sub(r"\s{2,}", " ", text).strip()


def _segment_with_text(seg: Any, text: str) -> Any:
    return SimpleNamespace(
        start=float(getattr(seg, "start", 0.0) or 0.0),
        end=float(getattr(seg, "end", 0.0) or 0.0),
        text=text,
        no_speech_prob=float(getattr(seg, "no_speech_prob", 0.0) or 0.0),
    )


def filter_segments(raw_segments: list) -> list:
    filtered = []
    for seg in raw_segments:
        text_strip = (seg.text or "").strip()
        if not text_strip:
            continue
        if seg.no_speech_prob > NO_SPEECH_PROB_THRESHOLD:
            continue
        if text_strip.lower() in HALLUCINATION_PHRASES:
            continue
        collapsed = collapse_repetitions(text_strip)
        if not collapsed:
            continue
        if (
            len(text_strip) > 80
            and len(collapsed) < 24
            and len(text_strip) >= 8 * max(len(collapsed), 1)
        ):
            continue
        if collapsed != text_strip:
            seg = _segment_with_text(seg, collapsed)
        filtered.append(seg)
    return filtered


def seconds_to_mmss(seconds: float) -> str:
    total = max(0, int(seconds))
    mm, ss = divmod(total, 60)
    return f"{mm:02d}:{ss:02d}"


def build_transcripcion_mmss(segments: list) -> str:
    if not segments:
        return ""
    blocks: list[str] = []
    current_words: list[str] = []
    block_start = float(segments[0].start)
    prev_end = float(segments[0].start)

    def flush() -> None:
        nonlocal current_words
        if not current_words:
            return
        body = collapse_repetitions(" ".join(current_words).strip())
        if body:
            blocks.append(f"[{seconds_to_mmss(block_start)}] {body}")
        current_words = []

    for seg in segments:
        text = collapse_repetitions(seg.text.strip())
        if not text:
            continue
        gap = float(seg.start) - prev_end
        if current_words and gap >= PAUSE_GAP_SEC:
            flush()
            block_start = float(seg.start)
        if not current_words:
            block_start = float(seg.start)
        current_words.append(text)
        prev_end = float(seg.end)
    flush()
    return "\n".join(blocks)


def parent_key(meta: dict) -> str:
    folder = (meta.get("folder_uuid") or "").strip()
    if folder:
        return folder
    return (meta.get("file_name") or meta.get("gcs_uri") or "").strip()


# ---------------------------------------------------------------------------
# BQ work items
# ---------------------------------------------------------------------------
def fetch_for_date(bq: bigquery.Client, process_date: str) -> list[dict]:
    sql = f"""
    SELECT
      fecha_audio AS process_date,
      gcs_uri,
      file_name,
      folder_uuid,
      gcs_path,
      duration_seconds,
      file_size_bytes
    FROM `{TABLE_CATALOG}`
    WHERE fecha_audio = @fecha
      AND gcs_uri IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY gcs_uri ORDER BY fecha_procesamiento DESC
    ) = 1
    ORDER BY folder_uuid, gcs_uri
    """
    rows = bq.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("fecha", "DATE", process_date)
            ]
        ),
    ).result()
    return [dict(r) for r in rows]


def fetch_for_uris(bq: bigquery.Client, uris: list[str]) -> list[dict]:
    sql = f"""
    SELECT
      fecha_audio AS process_date,
      gcs_uri,
      file_name,
      folder_uuid,
      gcs_path,
      duration_seconds,
      file_size_bytes
    FROM `{TABLE_CATALOG}`
    WHERE gcs_uri IN UNNEST(@uris)
    QUALIFY ROW_NUMBER() OVER (
      PARTITION BY gcs_uri ORDER BY fecha_procesamiento DESC
    ) = 1
    """
    found = {
        r["gcs_uri"]: dict(r)
        for r in bq.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("uris", "STRING", uris)
                ]
            ),
        ).result()
    }
    items = []
    for uri in uris:
        if uri in found:
            items.append(found[uri])
            continue
        base = os.path.basename(uri)
        items.append(
            {
                "process_date": date.today().isoformat(),
                "gcs_uri": uri,
                "file_name": base,
                "folder_uuid": None,
                "gcs_path": None,
                "duration_seconds": None,
                "file_size_bytes": None,
            }
        )
        logger.warning("URI sin metadata catálogo (stub): %s", uri)
    return items


# ---------------------------------------------------------------------------
# Whisper
# ---------------------------------------------------------------------------
def _ffprobe_duration_channels(src_path: str) -> tuple[float | None, int | None]:
    """Duración (s) y canales vía ffprobe sin decodificar todo el audio."""
    try:
        dur = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                src_path,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        ch = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=channels",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                src_path,
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        duration_s = float((dur.stdout or "").strip() or "nan")
        channels = int((ch.stdout or "").strip() or "0")
        if duration_s != duration_s or channels < 1:
            return None, None
        return duration_s, channels
    except Exception:  # noqa: BLE001
        return None, None


def probe_audio(src_path: str) -> tuple[int, int]:
    """Duración (ms) y canales. Prefiere ffprobe; fallback pydub."""
    duration_s, channels = _ffprobe_duration_channels(src_path)
    if duration_s is not None and channels is not None:
        return int(duration_s * 1000), channels
    audio = AudioSegment.from_file(src_path)
    return len(audio), audio.channels


def ensure_mono_wav(src_path: str, wav_path: str) -> tuple[int, int]:
    """Convierte a WAV mono solo cuando hace falta (estéreo o force)."""
    audio = AudioSegment.from_file(src_path)
    channels = audio.channels
    if channels > 1:
        logger.warning("  Audio con %s canales; se mezcla a mono.", channels)
        audio = audio.set_channels(1)
    audio.export(wav_path, format="wav")
    return len(audio), channels


def resolve_transcribe_path(src_path: str, tmpdir: str) -> tuple[str, int, int]:
    """
    Preferir archivo original (Whisper+ffmpeg leen m4a/mp3/flac directo).
    Solo exportar WAV mono si hay >1 canal o WHISPER_FORCE_MONO_WAV=1.
    """
    duration_ms, channels_original = probe_audio(src_path)
    suffix = Path(src_path).suffix.lower()
    need_wav = (
        WHISPER_FORCE_MONO_WAV
        or channels_original > 1
        or suffix not in _DIRECT_AUDIO_SUFFIXES
    )
    if not need_wav:
        return src_path, duration_ms, channels_original
    wav_path = os.path.join(tmpdir, f"{Path(src_path).stem}_mono.wav")
    duration_ms, channels_original = ensure_mono_wav(src_path, wav_path)
    return wav_path, duration_ms, channels_original


def transcribe_uri(
    storage_client: storage.Client,
    meta: dict,
    tmpdir: str,
    model: WhisperModel,
) -> dict:
    uri = meta["gcs_uri"]
    process_date = meta.get("process_date")
    if hasattr(process_date, "isoformat"):
        process_date = process_date.isoformat()

    bucket_name, blob_name = uri[5:].split("/", 1)
    suffix = Path(blob_name).suffix.lower() or ".m4a"
    local_audio = os.path.join(tmpdir, f"{Path(blob_name).stem}{suffix}")
    storage_client.bucket(bucket_name).blob(blob_name).download_to_filename(local_audio)

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    def row(
        *,
        status: str,
        transcripcion: str | None,
        duration_seconds: float | None,
        payload: dict,
        observaciones: str,
    ) -> dict:
        return {
            "fecha_audio": process_date or date.today().isoformat(),
            "gcs_uri": uri,
            "file_name": meta.get("file_name"),
            "folder_uuid": meta.get("folder_uuid"),
            "gcs_path": meta.get("gcs_path"),
            "file_size_bytes": meta.get("file_size_bytes"),
            "duration_seconds": duration_seconds,
            "status": status,
            "transcripcion": transcripcion,
            "idioma": "es",
            "canal": CITA_CANAL,
            "json_text": json.dumps(payload, ensure_ascii=False),
            "observaciones": observaciones,
            "load_date": now_utc,
            "_parent_key": parent_key(meta),
        }

    try:
        audio_path, duration_ms, channels = resolve_transcribe_path(local_audio, tmpdir)
    except Exception as exc:  # noqa: BLE001
        logger.error("Audio ilegible %s: %s", uri, exc, exc_info=True)
        return row(
            status="CORRUPT",
            transcripcion=None,
            duration_seconds=meta.get("duration_seconds"),
            payload={"error": f"audio_load_failed: {exc}"},
            observaciones=f"whisper:{WHISPER_MODEL};error=audio_load",
        )

    if duration_ms < 500:
        return row(
            status="EMPTY",
            transcripcion=None,
            duration_seconds=round(duration_ms / 1000.0, 3),
            payload={"error": "too_short_or_silent", "duration_ms": duration_ms},
            observaciones=f"whisper:{WHISPER_MODEL};silent_or_short",
        )

    try:
        segments_iter, info = model.transcribe(
            audio_path,
            language="es",
            task="transcribe",
            word_timestamps=WHISPER_WORD_TIMESTAMPS,
            initial_prompt=WHISPER_INITIAL_PROMPT,
            condition_on_previous_text=WHISPER_CONDITION_ON_PREVIOUS,
            temperature=0.0,
            beam_size=WHISPER_BEAM_SIZE,
            compression_ratio_threshold=2.4,
            vad_filter=True,
            vad_parameters=dict(
                threshold=0.5,
                min_speech_duration_ms=250,
                max_speech_duration_s=float("inf"),
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
        )
        raw_segments = list(segments_iter)
    except Exception as exc:  # noqa: BLE001
        logger.error("Whisper falló %s: %s", uri, exc, exc_info=True)
        return row(
            status="ERROR",
            transcripcion=None,
            duration_seconds=round(duration_ms / 1000.0, 3),
            payload={"error": f"transcribe_failed: {exc}"},
            observaciones=f"whisper:{WHISPER_MODEL};error=transcribe",
        )

    segments = filter_segments(raw_segments)
    transcripcion = build_transcripcion_mmss(segments)
    duration_seconds = meta.get("duration_seconds")
    if duration_seconds is None:
        duration_seconds = round(duration_ms / 1000.0, 3)

    payload = {
        "engine": "faster-whisper",
        "model": WHISPER_MODEL,
        "canal": CITA_CANAL,
        "language": getattr(info, "language", "es"),
        "duration": getattr(info, "duration", duration_ms / 1000.0),
        "segments_raw": len(raw_segments),
        "segments_kept": len(segments),
        "channels_original": channels,
        "beam_size": WHISPER_BEAM_SIZE,
        "audio_direct": audio_path == local_audio,
    }
    return row(
        status="OK" if transcripcion else "EMPTY",
        transcripcion=transcripcion,
        duration_seconds=duration_seconds,
        payload=payload,
        observaciones=f"whisper:{WHISPER_MODEL};canal={CITA_CANAL}",
    )


def load_rows(bq: bigquery.Client, rows: list[dict]) -> None:
    if not rows:
        return
    uris = [r["gcs_uri"] for r in rows]
    parents = sorted({r["_parent_key"] for r in rows if r.get("_parent_key")})

    bq.query(
        f"DELETE FROM `{TABLE_RAW}` WHERE gcs_uri IN UNNEST(@uris)",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("uris", "STRING", uris)]
        ),
    ).result()

    payload = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
    tmp = f"{PROJECT}.{DATASET}.tmp_cita_whisper_{int(time.time())}_{os.getpid()}"
    schema = [
        bigquery.SchemaField("fecha_audio", "DATE"),
        bigquery.SchemaField("gcs_uri", "STRING"),
        bigquery.SchemaField("file_name", "STRING"),
        bigquery.SchemaField("folder_uuid", "STRING"),
        bigquery.SchemaField("gcs_path", "STRING"),
        bigquery.SchemaField("file_size_bytes", "INT64"),
        bigquery.SchemaField("duration_seconds", "FLOAT64"),
        bigquery.SchemaField("status", "STRING"),
        bigquery.SchemaField("transcripcion", "STRING"),
        bigquery.SchemaField("idioma", "STRING"),
        bigquery.SchemaField("canal", "STRING"),
        bigquery.SchemaField("json_text", "STRING"),
        bigquery.SchemaField("observaciones", "STRING"),
        bigquery.SchemaField("load_date", "DATETIME"),
    ]
    bq.load_table_from_json(
        payload,
        tmp,
        job_config=bigquery.LoadJobConfig(
            schema=schema,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ),
    ).result()
    bq.query(
        f"""
        INSERT INTO `{TABLE_RAW}` (
          fecha_audio, gcs_uri, file_name, folder_uuid, gcs_path,
          file_size_bytes, duration_seconds, status, transcripcion,
          idioma, canal, json_text, observaciones, load_date
        )
        SELECT
          fecha_audio, gcs_uri, file_name, folder_uuid, gcs_path,
          file_size_bytes, duration_seconds, status, transcripcion,
          idioma, canal, json_text, observaciones, load_date
        FROM `{tmp}`
        """
    ).result()
    bq.delete_table(tmp, not_found_ok=True)
    logger.info("RAW: INSERT %s fila(s)", len(payload))

    if not parents:
        return

    bq.query(
        f"""
        DELETE FROM `{TABLE_PRD}`
        WHERE folder_uuid IN UNNEST(@parents)
           OR gcs_uri IN UNNEST(@uris)
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("parents", "STRING", parents),
                bigquery.ArrayQueryParameter("uris", "STRING", uris),
            ]
        ),
    ).result()

    bq.query(
        f"""
        INSERT INTO `{TABLE_PRD}` (
          fecha_audio, gcs_uri, file_name, folder_uuid, gcs_path,
          file_size_bytes, duration_seconds, status, transcripcion,
          idioma, canal, observaciones, load_date
        )
        WITH base AS (
          SELECT *
          FROM `{TABLE_RAW}`
          WHERE gcs_uri IN UNNEST(@uris)
             OR COALESCE(folder_uuid, file_name) IN UNNEST(@parents)
        ),
        keyed AS (
          SELECT
            *,
            COALESCE(NULLIF(TRIM(folder_uuid), ''), file_name, gcs_uri) AS parent_key
          FROM base
        ),
        merged AS (
          SELECT
            parent_key AS folder_uuid,
            ANY_VALUE(fecha_audio) AS fecha_audio,
            MIN(gcs_uri) AS gcs_uri,
            ANY_VALUE(file_name) AS file_name,
            ANY_VALUE(gcs_path) AS gcs_path,
            SUM(file_size_bytes) AS file_size_bytes,
            SUM(duration_seconds) AS duration_seconds,
            ANY_VALUE(status) AS status,
            STRING_AGG(
              NULLIF(TRIM(transcripcion), ''),
              '\\n'
              ORDER BY gcs_uri
            ) AS transcripcion,
            ANY_VALUE(idioma) AS idioma,
            ANY_VALUE(canal) AS canal,
            ANY_VALUE(observaciones) AS observaciones,
            MAX(load_date) AS load_date
          FROM keyed
          WHERE parent_key IN UNNEST(@parents)
          GROUP BY parent_key
        )
        SELECT
          fecha_audio, gcs_uri, file_name, folder_uuid, gcs_path,
          file_size_bytes, duration_seconds, status, transcripcion,
          idioma, canal, observaciones, load_date
        FROM merged
        WHERE NULLIF(TRIM(transcripcion), '') IS NOT NULL
        """,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("parents", "STRING", parents),
                bigquery.ArrayQueryParameter("uris", "STRING", uris),
            ]
        ),
    ).result()
    logger.info("PRD: rebuild %s padre(s)", len(parents))


def main() -> None:
    is_list = bool(GCS_URIS)
    is_day = bool(FECHA_AUDIO)
    if not is_list and not is_day:
        raise ValueError("Requiere FECHA_AUDIO=YYYY-MM-DD o GCS_URIS=gs://…")
    if is_day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", FECHA_AUDIO):
        raise ValueError(f"FECHA_AUDIO inválida: {FECHA_AUDIO!r}")

    logger.info(
        "=== Cita Whisper canal=%s modo=%s ===",
        CITA_CANAL,
        f"LISTA" if is_list else f"DÍA {FECHA_AUDIO}",
    )

    mapped = MODEL_MAP.get(WHISPER_MODEL, WHISPER_MODEL)
    t0 = time.time()
    model_kwargs: dict[str, Any] = {
        "device": "cpu",
        "compute_type": "int8",
        "cpu_threads": WHISPER_CPU_THREADS,
        "num_workers": WHISPER_NUM_WORKERS,
        "download_root": WHISPER_DOWNLOAD_ROOT,
        "local_files_only": _env_bool("HF_HUB_OFFLINE", True),
    }
    try:
        model = WhisperModel(mapped, **model_kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Whisper local_files_only falló (%s); reintento con descarga permitida",
            exc,
        )
        model_kwargs["local_files_only"] = False
        model = WhisperModel(mapped, **model_kwargs)
    logger.info(
        "Whisper '%s' root=%s offline=%s threads=%s beam=%s en %.1fs",
        mapped,
        WHISPER_DOWNLOAD_ROOT,
        model_kwargs["local_files_only"],
        WHISPER_CPU_THREADS,
        WHISPER_BEAM_SIZE,
        time.time() - t0,
    )

    storage_client = storage.Client(project=PROJECT)
    bq_client = bigquery.Client(project=PROJECT)

    if is_list:
        uris = [u.strip() for u in GCS_URIS.split(",") if u.strip()]
        work_items = fetch_for_uris(bq_client, uris)
    else:
        work_items = fetch_for_date(bq_client, FECHA_AUDIO)

    if not work_items:
        logger.warning("Sin audios. Fin.")
        return

    parents_order: list[str] = []
    by_parent: dict[str, list[dict]] = {}
    for item in work_items:
        pk = parent_key(item)
        if pk not in by_parent:
            by_parent[pk] = []
            parents_order.append(pk)
        by_parent[pk].append(item)

    task_index = int(os.environ.get("CLOUD_RUN_TASK_INDEX", "0"))
    task_count = int(os.environ.get("CLOUD_RUN_TASK_COUNT", "1"))
    my_parents = [
        p for idx, p in enumerate(parents_order) if idx % task_count == task_index
    ]
    logger.info(
        "Tarea %s/%s → %s padres de %s (archivos=%s)",
        task_index,
        task_count,
        len(my_parents),
        len(parents_order),
        len(work_items),
    )
    if not my_parents:
        return

    rows: list[dict] = []
    for p_idx, parent in enumerate(my_parents, start=1):
        segs = by_parent[parent]
        logger.info(
            "[Tarea %s | padre %s/%s] %s (%s archivo(s))",
            task_index,
            p_idx,
            len(my_parents),
            parent,
            len(segs),
        )
        for meta in segs:
            uri = meta["gcs_uri"]
            try:
                with tempfile.TemporaryDirectory() as tmpdir:
                    row = transcribe_uri(storage_client, meta, tmpdir, model)
                rows.append(row)
                logger.info(
                    "  ✓ %s status=%s chars=%s",
                    uri,
                    row.get("status"),
                    len(row.get("transcripcion") or ""),
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("  ✗ %s: %s", uri, exc, exc_info=True)

    if rows:
        load_rows(bq_client, rows)
    logger.info("=== Fin | %s filas → %s ===", len(rows), TABLE_RAW)


if __name__ == "__main__":
    main()
