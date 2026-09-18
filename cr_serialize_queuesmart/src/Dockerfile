# ============================================================
# Dockerfile — cr_serialize_queuesmart
# Cloud Run Job: Whisper LOCAL QueueSmart Counter (VASO)
# Modelo turbo embebido en la imagen (sin descarga en runtime).
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

ENV HF_HOME=/app/models
ENV HUGGINGFACE_HUB_CACHE=/app/models
ENV TRANSFORMERS_CACHE=/app/models

COPY requirements.txt .
RUN pip install --upgrade pip setuptools && \
    pip install --no-cache-dir -r requirements.txt

# Bake faster-whisper turbo (~800MB) into the image → no HF download at Job start
RUN mkdir -p /app/models && \
    python -c "from faster_whisper import WhisperModel; WhisperModel('deepdml/faster-whisper-large-v3-turbo-ct2', device='cpu', compute_type='int8', download_root='/app/models')"

COPY config/ ./config/
COPY main.py .

ENV WHISPER_MODEL=turbo
ENV WHISPER_DOWNLOAD_ROOT=/app/models
ENV FECHA_AUDIO=""
ENV GCS_URIS=""
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

CMD ["python", "main.py"]
