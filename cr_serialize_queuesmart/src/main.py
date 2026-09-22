"""
cr_serialize_queuesmart/main.py
Cloud Run Job — Whisper LOCAL (VASO). Sin diarización de hablantes.

Escribe en tablas VASO (NO toca Chirp prod):
  - adf_speech_analytics.hist_queuesmart_mp3_whisper_vaso_raw
  - adf_speech_analytics.hist_queuesmart_mp3_whisper_vaso_prd

Lee por defecto (config vaso):
  - raw_queue_smart.queuesmart_mp3_enriched_vaso
  - raw_queue_smart.hist_queesmart_mp3_catalog_vaso
Override: QS_TABLE_ENRICHED / QS_TABLE_CATALOG

No ejecuta Gemini (eso sigue en sp_queuesmart_audio_analisis_ia_vaso).

Flujo:
  1. FECHA_AUDIO → audios del día desde enriched_vaso (+ fallback catálogo vaso)
     GCS_URIS   → lista explícita (pruebas), metadata desde BQ si existe
  2. Particiona por source_file_name (padre) para no partir segmentos _s01/_s02
  3. faster-whisper → transcripcion [MM:SS] (contrato Counter)
  4. DELETE+INSERT raw por gcs_uri; rebuild prd fusionando segmentos del padre

Audio Counter: FLAC mono 16 kHz. transcripcion_con_hablantes queda NULL
(Whisper no identifica hablantes; diarización comercial queda fuera de scope).
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

# Overrides Cloud Build / Cloud Run (DEV/PRD vía activador)
if os.environ.get("GCP_PROJECT_ID"):
    GCP["project_id"] = os.environ["GCP_PROJECT_ID"].strip()
if os.environ.get("GCP_BUCKET_AUDIO"):
    GCP["bucket_audio"] = os.environ["GCP_BUCKET_AUDIO"].strip()
if os.environ.get("GCP_REGION"):
    GCP["region"] = os.environ["GCP_REGION"].strip()
if os.environ.get("GCP_JOB_NAME"):
    GCP["cloud_run_job_name"] = os.environ["GCP_JOB_NAME"].strip()
if os.environ.get("GCP_SERVICE_ACCOUNT_EMAIL"):
    GCP["service_account_email"] = os.environ["GCP_SERVICE_ACCOUNT_EMAIL"].strip()
if os.environ.get("QS_DATASET_RAW_QUEUE"):
    GCP["dataset_raw_queue"] = os.environ["QS_DATASET_RAW_QUEUE"].strip()
if os.environ.get("QS_DATASET_HIST"):
    GCP["dataset_hist"] = os.environ["QS_DATASET_HIST"].strip()
if os.environ.get("QS_TABLE_HIST_RAW"):
    GCP["table_hist_raw"] = os.environ["QS_TABLE_HIST_RAW"].strip()
if os.environ.get("QS_TABLE_HIST_PRD"):
    GCP["table_hist_prd"] = os.environ["QS_TABLE_HIST_PRD"].strip()
if os.environ.get("QS_TABLE_ENRICHED"):
    GCP["table_enriched"] = os.environ["QS_TABLE_ENRICHED"].strip()
if os.environ.get("QS_TABLE_CATALOG"):
    GCP["table_catalog"] = os.environ["QS_TABLE_CATALOG"].strip()

PROJECT = GCP["project_id"]

FECHA_AUDIO = os.environ.get("FECHA_AUDIO", "").strip()
GCS_URIS = os.environ.get("GCS_URIS", "").strip()
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "turbo").strip() or "turbo"

# Rendimiento (CPU). Defaults orientados a lote Counter (~200/día).
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
# Counter suele ser FLAC/WAV mono: no re-exportar a WAV salvo multi-canal.
WHISPER_FORCE_MONO_WAV = _env_bool("WHISPER_FORCE_MONO_WAV", False)
WHISPER_DEVICE = (os.environ.get("WHISPER_DEVICE", "cpu").strip().lower() or "cpu")
if WHISPER_DEVICE not in ("cpu", "cuda"):
    raise ValueError(f"WHISPER_DEVICE inválido: {WHISPER_DEVICE!r} (cpu|cuda)")
_DEFAULT_COMPUTE = "float16" if WHISPER_DEVICE == "cuda" else "int8"
WHISPER_COMPUTE_TYPE = (
    os.environ.get("WHISPER_COMPUTE_TYPE", "").strip() or _DEFAULT_COMPUTE
)
_DIRECT_AUDIO_SUFFIXES = {".flac", ".wav", ".mp3", ".m4a", ".ogg", ".opus", ".webm"}

# Sesgo léxico Whisper: español peruano + dominio Counter UTP.
# Sobrescribible con WHISPER_INITIAL_PROMPT (Cloud Run / Cloud Build).
# Mantener corto: Whisper solo usa ~224 tokens del prompt.
_DEFAULT_WHISPER_INITIAL_PROMPT = (
    "Conversación presencial en un counter de la Universidad Tecnológica del Perú (UTP), "
    "en español de Perú (variedades de distintas regiones: costa, sierra y selva). "
    "Hablan un asesor de admisiones y un postulante o apoderado. "
    "Vocabulario frecuente: matrícula, pensión, boleta, voucher, Yape, Plin, agente BCP, "
    "carrera, modalidad a distancia, semipresencial, turno noche, malla curricular, "
    "convalidación, documentos, DNI, constancia de estudios, certificado de notas, "
    "examen de admisión, Pronabec, Beca 18, descuento, vacante, inscripción, campus. "
    "Tratamiento de usted/tú según el diálogo. No inventar palabras en inglés."
)
WHISPER_INITIAL_PROMPT = (
    os.environ.get("WHISPER_INITIAL_PROMPT", "").strip() or _DEFAULT_WHISPER_INITIAL_PROMPT
)

PAUSE_GAP_SEC = 0.8
NO_SPEECH_PROB_THRESHOLD = 0.60

HALLUCINATION_PHRASES = {
    "gracias por ver el video",
    "gracias por ver el video.",
    "gracias por ver",
    "gracias por ver.",
    "gracias por su atención",
    "gracias por su atención.",
    "subtítulos por la comunidad de amara.org",
    "subtítulos por",
    "gracias por ver el vídeo",
    "gracias por ver el vídeo.",
    "suscríbete al canal",
    "suscríbete al canal.",
    "no olvides suscribirte",
    "no te olvides de suscribirte",
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

TABLE_RAW = f"{PROJECT}.{GCP['dataset_hist']}.{GCP['table_hist_raw']}"
TABLE_PRD = f"{PROJECT}.{GCP['dataset_hist']}.{GCP['table_hist_prd']}"
TABLE_ENRICHED = f"{PROJECT}.{GCP['dataset_raw_queue']}.{GCP['table_enriched']}"
TABLE_CATALOG = f"{PROJECT}.{GCP['dataset_raw_queue']}.{GCP['table_catalog']}"

logger.info(
    "Config GCP project=%s bucket=%s VASO raw=%s prd=%s (no hist Chirp)",
    PROJECT,
    GCP.get("bucket_audio"),
    TABLE_RAW,
    TABLE_PRD,
)


# ---------------------------------------------------------------------------
# Anti-alucinación / colapso de bucles (Whisper CPU)
# ---------------------------------------------------------------------------
# El loop clásico no empieza al inicio del segmento ("Bueno, en este caso, en este
# caso…", "certificado de certificado de…", "sí, sí, sí…"). Antes se descartaba
# el segmento entero; ahora se colapsa la repetición y se conserva el resto.

_MAX_PHRASE_LEN = 8
# Conservador para evaluación Gemini: solo bucles patológicos de Whisper.
# 2 repeticiones reales ("sí, sí" / "claro, claro") NO se tocan.
_COLLAPSE_MIN_REPS = 4
_COLLAPSE_MAX_KEEP = 2
# Monosílabos / muletillas: hace falta más repetición para colapsar
_SHORT_TOKEN_MIN_REPS = 6


def collapse_repetitions(text: str, *, max_keep: int = _COLLAPSE_MAX_KEEP) -> str:
    """
    Colapsa n-gramas consecutivos claramente alucinados (Whisper loop).
    Conserva 2 copias para no inventar ni borrar énfasis real del counter.
    No toca 2 repeticiones normales ("sí, sí", "ya, ya").
    """
    if not text or not text.strip():
        return text

    words = text.split()
    if len(words) >= 4:
        words = _collapse_word_runs(words, max_keep=max_keep)
        text = " ".join(words)

    # 008-008-008 / 945-945-945 (token con separador, ≥3 copias)
    text = re.sub(
        r"\b([A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]{1,24})(?:\s*([-/_,.])\s*\1){2,}\b",
        lambda m: (m.group(1) + m.group(2)) * (max_keep - 1) + m.group(1),
        text,
    )
    text = re.sub(r"\s{2,}", " ", text).strip()
    return text


def _norm_token(w: str) -> str:
    return re.sub(r"[^\wáéíóúüñÁÉÍÓÚÜÑ]+", "", w, flags=re.UNICODE).lower()


def _min_reps_for_phrase(phrase: list[str]) -> int:
    """Muletillas de 1 token necesitan más reps; frases largas bastan con 4."""
    if len(phrase) == 1 and len(_norm_token(phrase[0])) <= 4:
        return _SHORT_TOKEN_MIN_REPS
    return _COLLAPSE_MIN_REPS


def _collapse_word_runs(words: list[str], *, max_keep: int) -> list[str]:
    n = len(words)
    out: list[str] = []
    i = 0
    while i < n:
        max_len = min(_MAX_PHRASE_LEN, (n - i) // 3)
        # Preferir el patrón con MÁS repeticiones (unidad más pequeña del loop).
        best: tuple[int, int, int, list[str]] | None = None  # reps, -len, j, phrase
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
            _reps, _neg_len, j, phrase = best
            keep = min(_reps, max_keep)
            for _ in range(keep):
                out.extend(phrase)
            i = j
        else:
            out.append(words[i])
            i += 1
    return out


def _segment_with_text(seg: Any, text: str) -> Any:
    return SimpleNamespace(
        id=getattr(seg, "id", None),
        seek=getattr(seg, "seek", None),
        start=float(getattr(seg, "start", 0.0) or 0.0),
        end=float(getattr(seg, "end", 0.0) or 0.0),
        text=text,
        tokens=getattr(seg, "tokens", None),
        avg_logprob=getattr(seg, "avg_logprob", None),
        compression_ratio=getattr(seg, "compression_ratio", None),
        no_speech_prob=float(getattr(seg, "no_speech_prob", 0.0) or 0.0),
    )


def filter_segments(raw_segments: list) -> list:
    filtered = []
    for seg in raw_segments:
        text_strip = (seg.text or "").strip()
        if not text_strip:
            continue
        text_lower = text_strip.lower()
        if seg.no_speech_prob > NO_SPEECH_PROB_THRESHOLD:
            continue
        if text_lower in HALLUCINATION_PHRASES:
            continue

        collapsed = collapse_repetitions(text_strip)
        # Si tras colapsar queda casi vacío o solo basura muy corta de loop puro → drop
        if not collapsed.strip():
            continue
        # Ratio extremo: texto original >> colapsado (bucle masivo) y colapsado muy corto
        if (
            len(text_strip) > 80
            and len(collapsed) < 24
            and len(text_strip) >= 8 * max(len(collapsed), 1)
        ):
            logger.info(
                "  Drop segmento loop extremo (%.1fs-%.1fs) raw=%s collapsed=%s",
                float(seg.start),
                float(seg.end),
                len(text_strip),
                len(collapsed),
            )
            continue

        if collapsed != text_strip:
            logger.debug(
                "  Collapse loop %.1fs-%.1fs: %s→%s chars",
                float(seg.start),
                float(seg.end),
                len(text_strip),
                len(collapsed),
            )
            seg = _segment_with_text(seg, collapsed)

        filtered.append(seg)

    consecutive_limit = 2
    short_text_threshold = 60
    gap_reset_sec = 30.0
    last_text = None
    last_text_end = 0.0
    consecutive_count = 0
    final_segments = []

    for seg in filtered:
        text_strip = seg.text.strip()
        is_short = len(text_strip) <= short_text_threshold
        if is_short and text_strip == last_text:
            gap = seg.start - last_text_end
            if gap > gap_reset_sec:
                consecutive_count = 1
            else:
                consecutive_count += 1
                if consecutive_count > consecutive_limit:
                    last_text_end = seg.end
                    continue
        else:
            last_text = text_strip
            consecutive_count = 1
        last_text_end = seg.end
        final_segments.append(seg)

    return final_segments


# ---------------------------------------------------------------------------
# Texto [MM:SS]
# ---------------------------------------------------------------------------
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

    def flush():
        nonlocal current_words
        if not current_words:
            return
        stamp = seconds_to_mmss(block_start)
        body = collapse_repetitions(" ".join(current_words).strip())
        if body:
            blocks.append(f"[{stamp}] {body}")
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


def parent_key_from_names(source_file_name: str | None, file_name: str | None) -> str:
    src = (source_file_name or "").strip()
    if src:
        return src
    fn = (file_name or "").strip()
    return re.sub(r"_s\d+\.", ".", fn) if fn else ""


def segment_ord_from_file_name(file_name: str | None) -> int | None:
    if not file_name:
        return None
    m = re.search(r"_s(\d+)\.", file_name, flags=re.IGNORECASE)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Metadata desde BQ (mismo universo que el SP Chirp)
# ---------------------------------------------------------------------------
def fetch_work_items_for_date(bq_client: bigquery.Client, process_date: str) -> list[dict]:
    """Replica la selección de audios del SP gen_ia: enriched + fallback catálogo."""
    sql = f"""
    WITH enriched AS (
      SELECT
        e.process_day AS process_date,
        e.gcs_uri,
        e.file_name,
        COALESCE(e.source_file_name, e.file_name) AS source_file_name,
        COALESCE(e.audio, e.source_file_name, e.file_name) AS audio,
        e.recordid,
        e.rowid,
        e.codagencia,
        CAST(NULL AS STRING) AS gcs_path,
        e.campus_code,
        e.type_code,
        e.correlative,
        e.file_size_bytes,
        e.duration_seconds,
        CAST(NULL AS STRING) AS sync_mode,
        e.convert_method,
        CAST(NULL AS STRING) AS s3_uri,
        e.match_status,
        e.asesornombre,
        e.asesorusuario,
        e.asesorcodigo,
        e.ndoc,
        e.nombresusuario,
        e.numcelular,
        e.clientetipo,
        e.`database`
      FROM `{TABLE_ENRICHED}` AS e
      WHERE e.process_day = @fecha
        AND e.gcs_uri IS NOT NULL
    ),
    catalog_fallback AS (
      SELECT * EXCEPT(rn)
      FROM (
        SELECT
          c.fecha_audio AS process_date,
          c.gcs_uri,
          c.file_name,
          COALESCE(c.source_file_name, c.file_name) AS source_file_name,
          COALESCE(c.source_file_name, c.file_name) AS audio,
          CAST(NULL AS STRING) AS recordid,
          CAST(NULL AS INT64) AS rowid,
          CAST(NULL AS STRING) AS codagencia,
          c.gcs_path,
          c.campus_code,
          c.type_code,
          c.correlative,
          c.file_size_bytes,
          c.duration_seconds,
          c.sync_mode,
          c.convert_method,
          c.s3_uri,
          'GCS_ONLY' AS match_status,
          CAST(NULL AS STRING) AS asesornombre,
          CAST(NULL AS STRING) AS asesorusuario,
          CAST(NULL AS STRING) AS asesorcodigo,
          CAST(NULL AS STRING) AS ndoc,
          CAST(NULL AS STRING) AS nombresusuario,
          CAST(NULL AS STRING) AS numcelular,
          CAST(NULL AS STRING) AS clientetipo,
          CAST(NULL AS STRING) AS `database`,
          ROW_NUMBER() OVER (
            PARTITION BY c.gcs_uri
            ORDER BY c.fecha_procesamiento DESC
          ) AS rn
        FROM `{TABLE_CATALOG}` AS c
        WHERE c.fecha_audio = @fecha
          AND c.gcs_uri IS NOT NULL
          AND c.gcs_uri NOT IN (SELECT gcs_uri FROM enriched)
      )
      WHERE rn = 1
    )
    SELECT * FROM enriched
    UNION ALL
    SELECT * FROM catalog_fallback
    ORDER BY source_file_name, file_name, gcs_uri
    """
    job = bq_client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("fecha", "DATE", process_date)]
        ),
    )
    return [dict(row.items()) for row in job.result()]


def fetch_work_items_for_uris(bq_client: bigquery.Client, uris: list[str]) -> list[dict]:
    """Metadata BQ por URI; si no hay fila, stub mínimo para poder transcribir igual."""
    sql = f"""
    WITH wanted AS (
      SELECT uri FROM UNNEST(@uris) AS uri
    ),
    enriched AS (
      SELECT
        COALESCE(e.process_day, CURRENT_DATE('America/Lima')) AS process_date,
        e.gcs_uri,
        e.file_name,
        COALESCE(e.source_file_name, e.file_name) AS source_file_name,
        COALESCE(e.audio, e.source_file_name, e.file_name) AS audio,
        e.recordid,
        e.rowid,
        e.codagencia,
        CAST(NULL AS STRING) AS gcs_path,
        e.campus_code,
        e.type_code,
        e.correlative,
        e.file_size_bytes,
        e.duration_seconds,
        CAST(NULL AS STRING) AS sync_mode,
        e.convert_method,
        CAST(NULL AS STRING) AS s3_uri,
        e.match_status,
        e.asesornombre,
        e.asesorusuario,
        e.asesorcodigo,
        e.ndoc,
        e.nombresusuario,
        e.numcelular,
        e.clientetipo,
        e.`database`
      FROM `{TABLE_ENRICHED}` AS e
      INNER JOIN wanted w ON w.uri = e.gcs_uri
    ),
    catalog AS (
      SELECT * EXCEPT(rn)
      FROM (
        SELECT
          COALESCE(c.fecha_audio, CURRENT_DATE('America/Lima')) AS process_date,
          c.gcs_uri,
          c.file_name,
          COALESCE(c.source_file_name, c.file_name) AS source_file_name,
          COALESCE(c.source_file_name, c.file_name) AS audio,
          CAST(NULL AS STRING) AS recordid,
          CAST(NULL AS INT64) AS rowid,
          CAST(NULL AS STRING) AS codagencia,
          c.gcs_path,
          c.campus_code,
          c.type_code,
          c.correlative,
          c.file_size_bytes,
          c.duration_seconds,
          c.sync_mode,
          c.convert_method,
          c.s3_uri,
          'GCS_ONLY' AS match_status,
          CAST(NULL AS STRING) AS asesornombre,
          CAST(NULL AS STRING) AS asesorusuario,
          CAST(NULL AS STRING) AS asesorcodigo,
          CAST(NULL AS STRING) AS ndoc,
          CAST(NULL AS STRING) AS nombresusuario,
          CAST(NULL AS STRING) AS numcelular,
          CAST(NULL AS STRING) AS clientetipo,
          CAST(NULL AS STRING) AS `database`,
          ROW_NUMBER() OVER (PARTITION BY c.gcs_uri ORDER BY c.fecha_procesamiento DESC) AS rn
        FROM `{TABLE_CATALOG}` AS c
        INNER JOIN wanted w ON w.uri = c.gcs_uri
        WHERE c.gcs_uri NOT IN (SELECT gcs_uri FROM enriched)
      )
      WHERE rn = 1
    )
    SELECT * FROM enriched
    UNION ALL
    SELECT * FROM catalog
    """
    job = bq_client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("uris", "STRING", uris)]
        ),
    )
    found = {row["gcs_uri"]: dict(row.items()) for row in job.result()}

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
                "source_file_name": re.sub(r"_s\d+\.", ".", base),
                "audio": re.sub(r"_s\d+\.", ".", base),
                "recordid": None,
                "rowid": None,
                "codagencia": None,
                "gcs_path": None,
                "campus_code": None,
                "type_code": None,
                "correlative": None,
                "file_size_bytes": None,
                "duration_seconds": None,
                "sync_mode": None,
                "convert_method": None,
                "s3_uri": None,
                "match_status": "GCS_ONLY",
                "asesornombre": None,
                "asesorusuario": None,
                "asesorcodigo": None,
                "ndoc": None,
                "nombresusuario": None,
                "numcelular": None,
                "clientetipo": None,
                "database": None,
            }
        )
        logger.warning("URI sin metadata BQ (stub): %s", uri)
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
        if duration_s != duration_s or channels < 1:  # NaN
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
    channels_original = audio.channels
    if channels_original > 1:
        logger.warning("  Audio con %s canales; se mezcla a mono.", channels_original)
        audio = audio.set_channels(1)
    audio.export(wav_path, format="wav")
    return len(audio), channels_original


def resolve_transcribe_path(src_path: str, tmpdir: str) -> tuple[str, int, int]:
    """
    Preferir archivo original (Whisper+ffmpeg leen FLAC/MP3 directo).
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


def _base_row(
    meta: dict,
    *,
    uri: str,
    process_date: str | None,
    duration_seconds: float | None,
    whisper_payload: dict[str, Any],
    status: str,
    transcripcion: str | None,
    transcripcion_con_hablantes: str | None,
    observaciones: str,
) -> dict:
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "process_date": process_date or date.today().isoformat(),
        "gcs_uri": uri,
        "file_name": meta.get("file_name"),
        "source_file_name": meta.get("source_file_name"),
        "audio": meta.get("audio"),
        "recordid": meta.get("recordid"),
        "rowid": meta.get("rowid"),
        "codagencia": meta.get("codagencia"),
        "gcs_path": meta.get("gcs_path"),
        "campus_code": meta.get("campus_code"),
        "type_code": meta.get("type_code"),
        "correlative": meta.get("correlative"),
        "file_size_bytes": meta.get("file_size_bytes"),
        "duration_seconds": duration_seconds,
        "sync_mode": meta.get("sync_mode"),
        "convert_method": meta.get("convert_method"),
        "s3_uri": meta.get("s3_uri"),
        "match_status": meta.get("match_status"),
        "asesornombre": meta.get("asesornombre"),
        "asesorusuario": meta.get("asesorusuario"),
        "asesorcodigo": meta.get("asesorcodigo"),
        "ndoc": meta.get("ndoc"),
        "nombresusuario": meta.get("nombresusuario"),
        "numcelular": meta.get("numcelular"),
        "clientetipo": meta.get("clientetipo"),
        "database": meta.get("database"),
        "json_text": json.dumps(whisper_payload, ensure_ascii=False),
        "full_response": json.dumps(whisper_payload, ensure_ascii=False),
        "status": status,
        "transcripcion": transcripcion,
        "transcripcion_con_hablantes": transcripcion_con_hablantes,
        "resumen": None,
        "intencion": None,
        "idioma": "es",
        "tono": None,
        "entidades": None,
        "observaciones": observaciones,
        "load_date": now_utc,
        "_parent_key": parent_key_from_names(meta.get("source_file_name"), meta.get("file_name")),
        "_segment_ord": segment_ord_from_file_name(meta.get("file_name")),
    }


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
    blob = storage_client.bucket(bucket_name).blob(blob_name)

    suffix = Path(blob_name).suffix.lower() or ".flac"
    local_audio = os.path.join(tmpdir, f"{Path(blob_name).stem}{suffix}")
    blob.download_to_filename(local_audio)

    try:
        audio_path, duration_ms, channels_original = resolve_transcribe_path(
            local_audio, tmpdir
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("  Audio corrupto/ilegible %s: %s", uri, exc, exc_info=True)
        return _base_row(
            meta,
            uri=uri,
            process_date=process_date,
            duration_seconds=meta.get("duration_seconds"),
            whisper_payload={
                "engine": "faster-whisper",
                "model": WHISPER_MODEL,
                "error": f"audio_load_failed: {exc}",
            },
            status="CORRUPT",
            transcripcion=None,
            transcripcion_con_hablantes=None,
            observaciones=f"whisper:{WHISPER_MODEL};error=audio_load",
        )

    if duration_ms < 500:
        logger.warning("  Audio casi silencio (%.0f ms): %s", duration_ms, uri)
        return _base_row(
            meta,
            uri=uri,
            process_date=process_date,
            duration_seconds=round(duration_ms / 1000.0, 3),
            whisper_payload={
                "engine": "faster-whisper",
                "model": WHISPER_MODEL,
                "duration_ms": duration_ms,
                "error": "too_short_or_silent",
            },
            status="EMPTY",
            transcripcion=None,
            transcripcion_con_hablantes=None,
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
            # Default Whisper 2.4; no bajar: riesgo de tirar segmentos válidos para evaluación
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
        logger.error("  Whisper falló %s: %s", uri, exc, exc_info=True)
        return _base_row(
            meta,
            uri=uri,
            process_date=process_date,
            duration_seconds=round(duration_ms / 1000.0, 3),
            whisper_payload={
                "engine": "faster-whisper",
                "model": WHISPER_MODEL,
                "error": f"transcribe_failed: {exc}",
            },
            status="ERROR",
            transcripcion=None,
            transcripcion_con_hablantes=None,
            observaciones=f"whisper:{WHISPER_MODEL};error=transcribe",
        )

    segments = filter_segments(raw_segments)
    transcripcion = build_transcripcion_mmss(segments)

    whisper_payload = {
        "engine": "faster-whisper",
        "model": WHISPER_MODEL,
        "language": getattr(info, "language", "es"),
        "locale_bias": "es-PE",
        "initial_prompt_preview": WHISPER_INITIAL_PROMPT[:160],
        "duration": getattr(info, "duration", duration_ms / 1000.0),
        "segments_raw": len(raw_segments),
        "segments_kept": len(segments),
        "channels_original": channels_original,
        "beam_size": WHISPER_BEAM_SIZE,
        "word_timestamps": WHISPER_WORD_TIMESTAMPS,
        "condition_on_previous_text": WHISPER_CONDITION_ON_PREVIOUS,
    }

    duration_seconds = meta.get("duration_seconds")
    if duration_seconds is None:
        duration_seconds = round(duration_ms / 1000.0, 3)

    return _base_row(
        meta,
        uri=uri,
        process_date=process_date,
        duration_seconds=duration_seconds,
        whisper_payload=whisper_payload,
        status="OK" if transcripcion else "EMPTY",
        transcripcion=transcripcion,
        transcripcion_con_hablantes=None,
        observaciones=f"whisper:{WHISPER_MODEL}",
    )


# ---------------------------------------------------------------------------
# Persistencia hist (mismas tablas STT)
# ---------------------------------------------------------------------------
def load_rows_to_hist(bq_client: bigquery.Client, rows: list[dict]) -> None:
    if not rows:
        return

    uris = [r["gcs_uri"] for r in rows]
    parents = sorted({r["_parent_key"] for r in rows if r.get("_parent_key")})

    # 1) RAW: replace por URI
    del_raw = f"DELETE FROM `{TABLE_RAW}` WHERE gcs_uri IN UNNEST(@uris)"
    bq_client.query(
        del_raw,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ArrayQueryParameter("uris", "STRING", uris)]
        ),
    ).result()
    logger.info("RAW: DELETE %s URI(s)", len(uris))

    raw_payload = []
    for r in rows:
        raw_payload.append({k: v for k, v in r.items() if not k.startswith("_")})

    # Load job necesita schema flexible; usamos insert vía JSON load a temp + INSERT
    # Más simple: load_table_from_json con autodetect parcial — mejor INSERT DML por lotes
    # Para volumen Counter usamos load a tabla temp + INSERT SELECT.
    tmp_table = f"{PROJECT}.{GCP['dataset_hist']}.tmp_qs_whisper_load_{int(time.time())}_{os.getpid()}"
    schema = [
        bigquery.SchemaField("process_date", "DATE"),
        bigquery.SchemaField("gcs_uri", "STRING"),
        bigquery.SchemaField("file_name", "STRING"),
        bigquery.SchemaField("source_file_name", "STRING"),
        bigquery.SchemaField("audio", "STRING"),
        bigquery.SchemaField("recordid", "STRING"),
        bigquery.SchemaField("rowid", "INT64"),
        bigquery.SchemaField("codagencia", "STRING"),
        bigquery.SchemaField("gcs_path", "STRING"),
        bigquery.SchemaField("campus_code", "STRING"),
        bigquery.SchemaField("type_code", "STRING"),
        bigquery.SchemaField("correlative", "STRING"),
        bigquery.SchemaField("file_size_bytes", "INT64"),
        bigquery.SchemaField("duration_seconds", "FLOAT64"),
        bigquery.SchemaField("sync_mode", "STRING"),
        bigquery.SchemaField("convert_method", "STRING"),
        bigquery.SchemaField("s3_uri", "STRING"),
        bigquery.SchemaField("match_status", "STRING"),
        bigquery.SchemaField("asesornombre", "STRING"),
        bigquery.SchemaField("asesorusuario", "STRING"),
        bigquery.SchemaField("asesorcodigo", "STRING"),
        bigquery.SchemaField("ndoc", "STRING"),
        bigquery.SchemaField("nombresusuario", "STRING"),
        bigquery.SchemaField("numcelular", "STRING"),
        bigquery.SchemaField("clientetipo", "STRING"),
        bigquery.SchemaField("database", "STRING"),
        bigquery.SchemaField("json_text", "STRING"),
        bigquery.SchemaField("full_response", "STRING"),
        bigquery.SchemaField("status", "STRING"),
        bigquery.SchemaField("transcripcion", "STRING"),
        bigquery.SchemaField("transcripcion_con_hablantes", "STRING"),
        bigquery.SchemaField("resumen", "STRING"),
        bigquery.SchemaField("intencion", "STRING"),
        bigquery.SchemaField("idioma", "STRING"),
        bigquery.SchemaField("tono", "STRING"),
        bigquery.SchemaField("entidades", "STRING"),
        bigquery.SchemaField("observaciones", "STRING"),
        bigquery.SchemaField("load_date", "DATETIME"),
    ]

    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    bq_client.load_table_from_json(raw_payload, tmp_table, job_config=job_config).result()

    insert_raw = f"""
    INSERT INTO `{TABLE_RAW}` (
      process_date, gcs_uri, file_name, source_file_name, audio,
      recordid, rowid, codagencia, gcs_path, campus_code, type_code, correlative,
      file_size_bytes, duration_seconds, sync_mode, convert_method, s3_uri, match_status,
      asesornombre, asesorusuario, asesorcodigo, ndoc, nombresusuario, numcelular,
      clientetipo, `database`, json_text, full_response, status,
      transcripcion, transcripcion_con_hablantes, resumen, intencion, idioma, tono,
      entidades, observaciones, load_date
    )
    SELECT
      process_date, gcs_uri, file_name, source_file_name, audio,
      recordid, rowid, codagencia, gcs_path, campus_code, type_code, correlative,
      file_size_bytes, duration_seconds, sync_mode, convert_method, s3_uri, match_status,
      asesornombre, asesorusuario, asesorcodigo, ndoc, nombresusuario, numcelular,
      clientetipo, `database`, json_text, full_response, status,
      transcripcion, transcripcion_con_hablantes, resumen, intencion, idioma, tono,
      entidades, observaciones, load_date
    FROM `{tmp_table}`
    """
    bq_client.query(insert_raw).result()
    bq_client.delete_table(tmp_table, not_found_ok=True)
    logger.info("RAW: INSERT %s fila(s)", len(raw_payload))

    if not parents:
        return

    # 2) PRD: rebuild padres (misma lógica de merge de segmentos que el SP)
    del_prd = f"""
    DELETE FROM `{TABLE_PRD}`
    WHERE source_file_name IN UNNEST(@parents)
       OR gcs_uri IN UNNEST(@uris)
    """
    bq_client.query(
        del_prd,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("parents", "STRING", parents),
                bigquery.ArrayQueryParameter("uris", "STRING", uris),
            ]
        ),
    ).result()

    insert_prd = f"""
    INSERT INTO `{TABLE_PRD}` (
      process_date, gcs_uri, file_name, source_file_name, audio,
      recordid, rowid, codagencia, campus_code, type_code, correlative,
      file_size_bytes, duration_seconds, match_status,
      asesornombre, asesorusuario, asesorcodigo, ndoc, nombresusuario, numcelular,
      clientetipo, `database`, transcripcion, transcripcion_con_hablantes,
      resumen, intencion, idioma, tono, entidades, observaciones, load_date
    )
    WITH base AS (
      SELECT *
      FROM `{TABLE_RAW}`
      WHERE gcs_uri IN UNNEST(@uris)
         OR source_file_name IN UNNEST(@parents)
    ),
    keyed AS (
      SELECT
        *,
        COALESCE(
          NULLIF(TRIM(source_file_name), ''),
          REGEXP_REPLACE(file_name, r'_s\\d+\\.', '.')
        ) AS stt_parent_key,
        SAFE_CAST(REGEXP_EXTRACT(file_name, r'_s(\\d+)\\.') AS INT64) AS segment_ord
      FROM base
    ),
    merged AS (
      SELECT
        stt_parent_key,
        ANY_VALUE(process_date) AS process_date,
        MIN(gcs_uri) AS gcs_uri,
        ANY_VALUE(source_file_name) AS source_file_name,
        ANY_VALUE(file_name) AS file_name,
        ANY_VALUE(audio) AS audio,
        ANY_VALUE(recordid) AS recordid,
        ANY_VALUE(rowid) AS rowid,
        ANY_VALUE(codagencia) AS codagencia,
        ANY_VALUE(campus_code) AS campus_code,
        ANY_VALUE(type_code) AS type_code,
        ANY_VALUE(correlative) AS correlative,
        SUM(file_size_bytes) AS file_size_bytes,
        SUM(duration_seconds) AS duration_seconds,
        ANY_VALUE(match_status) AS match_status,
        ANY_VALUE(asesornombre) AS asesornombre,
        ANY_VALUE(asesorusuario) AS asesorusuario,
        ANY_VALUE(asesorcodigo) AS asesorcodigo,
        ANY_VALUE(ndoc) AS ndoc,
        ANY_VALUE(nombresusuario) AS nombresusuario,
        ANY_VALUE(numcelular) AS numcelular,
        ANY_VALUE(clientetipo) AS clientetipo,
        ANY_VALUE(`database`) AS `database`,
        STRING_AGG(
          NULLIF(TRIM(transcripcion), ''),
          '\\n'
          ORDER BY segment_ord NULLS FIRST, gcs_uri
        ) AS transcripcion,
        STRING_AGG(
          NULLIF(TRIM(transcripcion_con_hablantes), ''),
          '\\n'
          ORDER BY segment_ord NULLS FIRST, gcs_uri
        ) AS transcripcion_con_hablantes,
        ANY_VALUE(resumen) AS resumen,
        ANY_VALUE(intencion) AS intencion,
        ANY_VALUE(idioma) AS idioma,
        ANY_VALUE(tono) AS tono,
        ANY_VALUE(entidades) AS entidades,
        ANY_VALUE(observaciones) AS observaciones,
        MAX(load_date) AS load_date
      FROM keyed
      WHERE stt_parent_key IN UNNEST(@parents)
      GROUP BY stt_parent_key
    )
    SELECT
      process_date, gcs_uri, file_name, source_file_name, audio,
      recordid, rowid, codagencia, campus_code, type_code, correlative,
      file_size_bytes, duration_seconds, match_status,
      asesornombre, asesorusuario, asesorcodigo, ndoc, nombresusuario, numcelular,
      clientetipo, `database`, transcripcion, transcripcion_con_hablantes,
      resumen, intencion, idioma, tono, entidades, observaciones, load_date
    FROM merged
    WHERE NULLIF(TRIM(transcripcion), '') IS NOT NULL
    """
    bq_client.query(
        insert_prd,
        job_config=bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter("parents", "STRING", parents),
                bigquery.ArrayQueryParameter("uris", "STRING", uris),
            ]
        ),
    ).result()
    logger.info("PRD: rebuild de %s padre(s)", len(parents))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    is_list = bool(GCS_URIS)
    is_day = bool(FECHA_AUDIO)

    if not is_list and not is_day:
        raise ValueError(
            "Requiere FECHA_AUDIO=YYYY-MM-DD o GCS_URIS=gs://a,gs://b"
        )
    if is_day and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", FECHA_AUDIO):
        raise ValueError(f"FECHA_AUDIO inválida: {FECHA_AUDIO!r}")

    logger.info(
        "=== QueueSmart Whisper → hist VASO | modo=%s ===",
        f"LISTA" if is_list else f"DÍA {FECHA_AUDIO}",
    )

    mapped = MODEL_MAP.get(WHISPER_MODEL, WHISPER_MODEL)
    t0 = time.time()
    model_kwargs: dict[str, Any] = {
        "device": WHISPER_DEVICE,
        "compute_type": WHISPER_COMPUTE_TYPE,
        "download_root": WHISPER_DOWNLOAD_ROOT,
        "local_files_only": _env_bool("HF_HUB_OFFLINE", True),
    }
    if WHISPER_DEVICE == "cpu":
        model_kwargs["cpu_threads"] = WHISPER_CPU_THREADS
        model_kwargs["num_workers"] = WHISPER_NUM_WORKERS
    try:
        model = WhisperModel(mapped, **model_kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Whisper load falló (%s); reintento local_files_only=False",
            exc,
        )
        model_kwargs["local_files_only"] = False
        model = WhisperModel(mapped, **model_kwargs)
    logger.info(
        "Whisper '%s' device=%s compute=%s root=%s offline=%s beam=%s en %.1fs",
        mapped,
        WHISPER_DEVICE,
        WHISPER_COMPUTE_TYPE,
        WHISPER_DOWNLOAD_ROOT,
        model_kwargs["local_files_only"],
        WHISPER_BEAM_SIZE,
        time.time() - t0,
    )

    storage_client = storage.Client(project=PROJECT)
    bq_client = bigquery.Client(project=PROJECT)

    if is_list:
        uris = [u.strip() for u in GCS_URIS.split(",") if u.strip()]
        work_items = fetch_work_items_for_uris(bq_client, uris)
    else:
        work_items = fetch_work_items_for_date(bq_client, FECHA_AUDIO)

    if not work_items:
        logger.warning("Sin audios para procesar. Fin.")
        return

    # Agrupar por padre para no partir _s01/_s02 entre tasks
    parents_order: list[str] = []
    by_parent: dict[str, list[dict]] = {}
    for item in work_items:
        pk = parent_key_from_names(item.get("source_file_name"), item.get("file_name"))
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
        "Tarea %s/%s → %s padres de %s (archivos día=%s)",
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
            "[Tarea %s | padre %s/%s] %s (%s segmento(s))",
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
            except Exception as e:
                logger.error("  ✗ %s: %s", uri, e, exc_info=True)

    if rows:
        load_rows_to_hist(bq_client, rows)
    else:
        logger.warning("Tarea %s: sin filas.", task_index)

    logger.info("=== Fin | %s segmentos cargados a hist VASO ===", len(rows))


if __name__ == "__main__":
    main()
