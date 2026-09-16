# ============================================================
# Dockerfile — cr_serialize_queuesmart
# Cloud Run Job: Whisper LOCAL QueueSmart Counter (VASO)
# ============================================================

FROM python:3.11-slim

LABEL maintainer="data-team@utpbi"
LABEL description="Cloud Run Job Whisper LOCAL QueueSmart Counter (VASO)"

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --upgrade pip setuptools && \
    pip install --no-cache-dir -r requirements.txt

# Pre-descargar modelo turbo (~800MB) en build → arranque determinista
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('deepdml/faster-whisper-large-v3-turbo-ct2', device='cpu', compute_type='int8')"

COPY config/ ./config/
COPY main.py .

ENV WHISPER_MODEL=turbo
ENV FECHA_AUDIO=""
ENV GCS_URIS=""

CMD ["python", "main.py"]
