#!/bin/bash
# Crea/actualiza Cloud Scheduler apuntando a la Cloud Function Gen2.
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
FUNCTION_NAME=$(jq -r '.gcp.function_name' "$CONFIG_FILE")

SCHEDULE="${SCHEDULE:-0 4 * * *}"
TIMEZONE="${TIMEZONE:-America/Lima}"
PAYLOAD="${PAYLOAD:-{\"current_date\": \"TODAY\", \"days_back\": 3}}"

gcloud config set project "$PROJECT_ID"
gcloud services enable cloudscheduler.googleapis.com cloudfunctions.googleapis.com

FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" \
  --region="$REGION" \
  --gen2 \
  --format='value(serviceConfig.uri)')

echo "Cloud Function URL: $FUNCTION_URL"

if gcloud scheduler jobs describe "$SCHEDULER_NAME" --location="$REGION" &>/dev/null; then
  gcloud scheduler jobs delete "$SCHEDULER_NAME" --location="$REGION" --quiet
fi

gcloud scheduler jobs create http "$SCHEDULER_NAME" \
  --location="$REGION" \
  --schedule="$SCHEDULE" \
  --time-zone="$TIMEZONE" \
  --uri="$FUNCTION_URL" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body="$PAYLOAD" \
  --description="ETL OneMarketer (reporte chats + medios) vía Cloud Function"

echo "Scheduler $SCHEDULER_NAME creado → $FUNCTION_URL"
