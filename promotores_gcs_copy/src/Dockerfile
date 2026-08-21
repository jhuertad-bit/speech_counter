FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ config/
COPY tablas/ tablas/
COPY config_loader.py dates.py gcs_copy.py secrets_loader.py manifest.py \
     prepare.py worker.py bq_catalog.py probe_audio.py main.py ./

ENV CONFIG_PATH=/app/config/config.json
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "main.py"]
