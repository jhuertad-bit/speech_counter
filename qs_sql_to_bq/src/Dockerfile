FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    freetds-dev \
    freetds-bin \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config/ config/
COPY tablas/ tablas/
COPY config_loader.py sql_client.py bq_loader.py audio_filter.py extract.py main.py ./

ENV CONFIG_PATH=/app/config/config.json
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "main.py"]
