#!/bin/bash
# Crea/actualiza Cloud Scheduler apuntando a la Cloud Function Gen2.
# Usa gcp.* de config/config.json (o overrides GCP_* si están exportadas en el shell).
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

# Overrides opcionales (mismos nombres que Cloud Build / Cloud Function)
PROJECT_ID="${GCP_PROJECT_ID:-$PROJECT_ID}"
REGION="${GCP_REGION:-$REGION}"
SCHEDULER_NAME="${GCP_SCHEDULER_NAME:-$SCHEDULER_NAME}"
FUNCTION_NAME="${GCP_FUNCTION_NAME:-$FUNCTION_NAME}"

SERVICE_ACCOUNT_NAME=$(jq -r '.gcp.service_account_name' "$CONFIG_FILE")
SERVICE_ACCOUNT_NAME="${GCP_SERVICE_ACCOUNT_NAME:-$SERVICE_ACCOUNT_NAME}"
INVOKER_SA="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

for var_name in PROJECT_ID REGION FUNCTION_NAME SCHEDULER_NAME SERVICE_ACCOUNT_NAME; do
  if [[ -z "${!var_name}" || "${!var_name}" == "null" ]]; then
    echo "ERROR: falta ${var_name}. Exporta las variables GCP_* o complétalas en config.json."
    exit 1
  fi
done

SCHEDULE="${SCHEDULE:-0 4 * * *}"
TIMEZONE="${TIMEZONE:-America/Lima}"
# YESTERDAY + days_back=0 → día anterior (job 4am Lima procesa el día cerrado). force_reprocess solo manual.
PAYLOAD="${PAYLOAD:-{\"current_date\": \"YESTERDAY\", \"days_back\": 0, \"force_reprocess\": false}}"

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
  --oidc-service-account-email="$INVOKER_SA" \
  --oidc-token-audience="$FUNCTION_URL" \
  --description="ETL OneMarketer (reporte chats + medios) vía Cloud Function (OIDC)"

echo "Scheduler $SCHEDULER_NAME creado → $FUNCTION_URL (invoker: $INVOKER_SA)"
