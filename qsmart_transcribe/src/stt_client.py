"""Speech-to-Text API v2 — chirp_3 + diarization (BatchRecognize)."""

from __future__ import annotations

from typing import Any

from google.api_core.client_options import ClientOptions
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech


def _speaker_label(tag: int | None) -> str:
    if tag is None:
        return "Persona ?"
    return f"Persona {int(tag)}"


def _word_speaker_tag(word: Any) -> int | None:
    """Chirp 3 v2: speaker_label ('1','2') o speaker_tag (int)."""
    label = getattr(word, "speaker_label", None)
    if label is not None and str(label).strip().isdigit():
        return int(label)
    tag = getattr(word, "speaker_tag", None)
    if tag:
        return int(tag)
    return None


def build_diarized_transcript(result: cloud_speech.BatchRecognizeResults) -> tuple[str, str]:
    """
    Retorna (texto_plano, texto_con_hablantes).

    Agrupa palabras consecutivas del mismo speakerTag en turnos:
      Persona 1: hola ...
      Persona 2: buenos días ...
    """
    plain_parts: list[str] = []
    diarized_lines: list[str] = []
    current_speaker: int | None = None
    current_words: list[str] = []

    def flush() -> None:
        nonlocal current_speaker, current_words
        if not current_words:
            return
        line = f"{_speaker_label(current_speaker)}: {' '.join(current_words).strip()}"
        diarized_lines.append(line)
        current_words = []

    for res in result.results:
        alt = res.alternatives[0] if res.alternatives else None
        if not alt:
            continue
        if alt.transcript:
            plain_parts.append(alt.transcript.strip())

        words = list(alt.words) if alt.words else []
        if not words:
            # Sin word-level speakers: no hay diarización usable
            continue
        for w in words:
            tag = _word_speaker_tag(w)
            word_text = (w.word or "").strip()
            if not word_text:
                continue
            if current_speaker is None:
                current_speaker = tag
            if tag != current_speaker:
                flush()
                current_speaker = tag
            current_words.append(word_text)

    flush()

    plain = " ".join(p for p in plain_parts if p).strip()
    diarized = "\n".join(diarized_lines).strip() if diarized_lines else ""
    return plain, diarized


def transcribe_gcs_uri(config: dict[str, Any], gcs_uri: str) -> dict[str, Any]:
    """
    BatchRecognize de 1 archivo GCS.

    Retorna:
      status, transcripcion, transcripcion_con_hablantes, full_response (dict-ish)
    """
    gcp = config["gcp"]
    stt = config.get("stt", {})
    project = gcp["project_id"]
    location = gcp.get("stt_location", "us")
    model = stt.get("model", "chirp_3")
    language_codes = stt.get("language_codes", ["es-US"])
    min_spk = int(stt.get("min_speaker_count", 2))
    max_spk = int(stt.get("max_speaker_count", 2))
    recognizer_id = stt.get("recognizer_id", "_")

    client = SpeechClient(
        client_options=ClientOptions(api_endpoint=f"{location}-speech.googleapis.com")
    )
    recognizer = f"projects/{project}/locations/{location}/recognizers/{recognizer_id}"

    recognition_config = cloud_speech.RecognitionConfig(
        auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
        language_codes=language_codes,
        model=model,
        features=cloud_speech.RecognitionFeatures(
            enable_automatic_punctuation=True,
            diarization_config=cloud_speech.SpeakerDiarizationConfig(
                min_speaker_count=min_spk,
                max_speaker_count=max_spk,
            ),
        ),
    )

    request = cloud_speech.BatchRecognizeRequest(
        recognizer=recognizer,
        config=recognition_config,
        files=[cloud_speech.BatchRecognizeFileMetadata(uri=gcs_uri)],
        recognition_output_config=cloud_speech.RecognitionOutputConfig(
            inline_response_config=cloud_speech.InlineOutputConfig(),
        ),
    )

    operation = client.batch_recognize(request=request)
    response = operation.result(timeout=int(stt.get("timeout_seconds", 1800)))

    file_result = response.results.get(gcs_uri)
    if file_result is None and response.results:
        # Algunas respuestas indexan sin el scheme exacto
        file_result = next(iter(response.results.values()))

    if file_result is None:
        return {
            "status": "ERROR: empty BatchRecognize results",
            "transcripcion": "",
            "transcripcion_con_hablantes": "",
            "full_response": {},
        }

    if file_result.error and file_result.error.message:
        return {
            "status": f"ERROR: {file_result.error.message}",
            "transcripcion": "",
            "transcripcion_con_hablantes": "",
            "full_response": {"error": file_result.error.message},
        }

    plain, diarized = build_diarized_transcript(file_result.transcript)
    return {
        "status": "OK",
        "transcripcion": plain,
        "transcripcion_con_hablantes": diarized or None,
        "full_response": cloud_speech.BatchRecognizeFileResult.to_dict(file_result),
    }
