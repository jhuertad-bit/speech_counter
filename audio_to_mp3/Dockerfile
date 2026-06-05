FROM python:3.11-slim

# ffmpeg + ffprobe (requeridos por converter.py / pydub)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV CONFIG_PATH=config/config.json

COPY src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código y configs (main.py busca config/ junto al módulo)
COPY src/converter.py src/main.py ./
COPY src/config/ ./config/

# Gen2 Cloud Function (Eventarc / GCS): functions-framework en modo CloudEvent
CMD ["sh", "-c", "exec functions-framework --target=audio_to_mp3_converter --port=${PORT:-8080} --signature-type=cloudevent"]
