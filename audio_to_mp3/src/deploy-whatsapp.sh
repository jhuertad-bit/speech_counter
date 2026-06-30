#!/bin/bash
# Despliega audio_to_mp3 para el bucket de WhatsApp (notas de voz).

set -e

CONFIG_FILE="config/config_whatsapp.json"
if [ ! -f "$CONFIG_FILE" ]; then
  echo "Error: no existe $CONFIG_FILE"
  exit 1
fi

PROJECT_ID=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['project_id'])")
BUCKET_NAME=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['bucket_name'])")
PATH_INPUT=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['path_audios_input'])")
FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['cloud_function_name'])")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['service_account_email'])")
REGION=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE'))['gcp']; print(c.get('region','us-central1'))")

gcloud config set project "$PROJECT_ID"
gcloud services enable cloudfunctions.googleapis.com eventarc.googleapis.com \
  cloudbuild.googleapis.com run.googleapis.com

gcloud functions deploy "$FUNCTION_NAME" \
  --gen2 \
  --runtime=python311 \
  --region="$REGION" \
  --source=. \
  --entry-point=audio_to_mp3_converter \
  --trigger-event-filters=type=google.cloud.storage.object.v1.finalized \
  --trigger-event-filters=bucket="$BUCKET_NAME" \
  --trigger-location="$REGION" \
  --service-account="$SERVICE_ACCOUNT" \
  --memory=6144MB \
  --timeout=540s \
  --max-instances=30 \
  --concurrency=1 \
  --set-env-vars="CONFIG_PATH=config/config_whatsapp.json" \
  --allow-unauthenticated

echo "Función $FUNCTION_NAME → gs://$BUCKET_NAME/$PATH_INPUT"
