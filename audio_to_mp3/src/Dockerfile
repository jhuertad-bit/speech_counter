FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1
ENV PORT=8080
ENV CONFIG_PATH=config/config.json

CMD ["sh", "-c", "exec functions-framework --target=audio_to_mp3_converter --port=${PORT:-8080} --signature-type=cloudevent"]
