FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ config/
COPY config_loader.py audio_paths.py bq_catalog.py sync.py secrets_loader.py main.py ./
COPY tablas/ tablas/

ENV CONFIG_PATH=/app/config/config.json

ENTRYPOINT ["python", "main.py"]
