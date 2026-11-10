# Build context = raíz speech_counter (incluye onemarketer-api/src).
# Activador propio: no redespliega el servicio HTTP onemarketer-api.
FROM python:3.10-slim

WORKDIR /app

COPY onemarketer-api/src/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Lógica ETL + fix lcra_* (fuente de verdad: onemarketer-api)
COPY onemarketer-api/src/ /app/src/

# Entrypoint del Job (carpeta separada)
COPY onemarketer_api_backfill/src/job_backfill.py /app/src/job_backfill.py

WORKDIR /app/src
ENV PYTHONUNBUFFERED=1

CMD ["python", "job_backfill.py"]
