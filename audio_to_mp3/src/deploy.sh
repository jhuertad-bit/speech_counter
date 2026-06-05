#!/bin/bash
# Despliega Cloud Function Gen2: conversión universal de audio a MP3.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

DRY_RUN=false
for arg in "$@"; do
  case $arg in
    --dry-run) DRY_RUN=true ;;
  esac
done

CONFIG_FILE="config/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
  echo -e "${RED}Error: no existe $CONFIG_FILE${NC}"
  exit 1
fi

PROJECT_ID=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['project_id'])")
BUCKET_NAME=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['bucket_name'])")
PATH_INPUT=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['path_audios_input'])")
FUNCTION_NAME=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['cloud_function_name'])")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['service_account_email'])")
REGION=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE'))['gcp']; print(c.get('region','us-central1'))")

echo -e "${GREEN}Proyecto:${NC} $PROJECT_ID"
echo -e "${GREEN}Función:${NC} $FUNCTION_NAME"
echo -e "${GREEN}Bucket:${NC} $BUCKET_NAME"
echo -e "${GREEN}Entrada:${NC} $PATH_INPUT"
echo ""

gcloud config set project "$PROJECT_ID"

gcloud services enable cloudfunctions.googleapis.com eventarc.googleapis.com \
  cloudbuild.googleapis.com run.googleapis.com artifactregistry.googleapis.com

DEPLOY_CMD="gcloud functions deploy $FUNCTION_NAME \
  --gen2 \
  --runtime=python311 \
  --region=$REGION \
  --source=. \
  --entry-point=audio_to_mp3_converter \
  --trigger-event-filters=type=google.cloud.storage.object.v1.finalized \
  --trigger-event-filters=bucket=$BUCKET_NAME \
  --trigger-location=$REGION \
  --service-account=$SERVICE_ACCOUNT \
  --memory=6144MB \
  --timeout=540s \
  --max-instances=30 \
  --min-instances=0 \
  --concurrency=1 \
  --set-env-vars=INPUT_PATH=$PATH_INPUT \
  --allow-unauthenticated"

if [ "$DRY_RUN" = true ]; then
  echo "$DEPLOY_CMD"
  exit 0
fi

eval "$DEPLOY_CMD"

echo -e "${GREEN}Despliegue completado${NC}"
echo "Se procesan audios en: gs://$BUCKET_NAME/$PATH_INPUT"
echo "Extensiones: ver config.audio.supported_extensions"
