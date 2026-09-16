# ============================================================
# Dockerfile — cr_serialize_queuesmart
# Cloud Run Job: Whisper LOCAL + pyannote diarization (VASO)
# ============================================================

FROM python:3.11-slim

LABEL maintainer="data-team@utpbi"
LABEL description="Cloud Run Job Whisper + pyannote QueueSmart Counter (VASO)"

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgomp1 \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Torch/torchaudio CPU primero (evita wheel CUDA enorme en Cloud Run sin GPU)
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir \
      torch==2.3.1 torchaudio==2.3.1 \
      --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt

# Pre-descargar modelo turbo (~800MB) en build → arranque determinista
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('deepdml/faster-whisper-large-v3-turbo-ct2', device='cpu', compute_type='int8')"

COPY config/ ./config/
COPY main.py .
COPY diarize.py .

ENV WHISPER_MODEL=turbo
ENV ENABLE_DIARIZATION=true
ENV DIARIZATION_STAMP_FORMAT=hms
ENV FECHA_AUDIO=""
ENV GCS_URIS=""
# HF_TOKEN / HUGGINGFACE_TOKEN inyectado en runtime (Secret Manager / env)
# Requiere aceptar condiciones de pyannote/speaker-diarization-3.1 en Hugging Face.

CMD ["python", "main.py"]
