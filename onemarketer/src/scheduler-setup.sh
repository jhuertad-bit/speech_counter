#!/bin/bash
# Crea/actualiza Cloud Scheduler apuntando al servicio Cloud Run (no Cloud Functions).
# Ejecutar desde onemarketer/src con: ./scheduler-setup.sh
set -euo pipefail

CONFIG_FILE="config/config.json"
if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "No se encontró $CONFIG_FILE"
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo "Instala jq: brew install jq"
  exit 1
fi

PROJECT_ID=$(jq -r '.gcp.project_id' "$CONFIG_FILE")
REGION=$(jq -r '.gcp.region' "$CONFIG_FILE")
SCHEDULER_NAME=$(jq -r '.gcp.scheduler_name' "$CONFIG_FILE")
SERVICE_NAME=$(jq -r '.gcp.function_name' "$CONFIG_FILE")

# Nombre del servicio Cloud Run (ajusta si difiere del function_name en config)
CLOUD_RUN_SERVICE="${CLOUD_RUN_SERVICE:-$SERVICE_NAME}"

SCHEDULE="${SCHEDULE:-0 4 * * *}"
TIMEZONE="${TIMEZONE:-America/Lima}"
PAYLOAD="${PAYLOAD:-{\"current_date\": \"TODAY\", \"days_back\": 3}}"

gcloud config set project "$PROJECT_ID"
gcloud services enable cloudscheduler.googleapis.com run.googleapis.com

SERVICE_URL=$(gcloud run services describe "$CLOUD_RUN_SERVICE" \
  --region="$REGION" \
  --format='value(status.url)')

echo "Cloud Run URL: $SERVICE_URL"

if gcloud scheduler jobs describe "$SCHEDULER_NAME" --location="$REGION" &>/dev/null; then
  gcloud scheduler jobs delete "$SCHEDULER_NAME" --location="$REGION" --quiet
fi

gcloud scheduler jobs create http "$SCHEDULER_NAME" \
  --location="$REGION" \
  --schedule="$SCHEDULE" \
  --time-zone="$TIMEZONE" \
  --uri="$SERVICE_URL" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body="$PAYLOAD" \
  --description="ETL OneMarketer (reporte chats + medios) vía Cloud Run"

echo "Scheduler $SCHEDULER_NAME creado → $SERVICE_URL"
