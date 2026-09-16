#!/bin/bash
# Crea o actualiza Cloud Scheduler para ejecutar el Cloud Run Job cada hora.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

CONFIG_FILE="config/config.json"

if [ ! -f "$CONFIG_FILE" ]; then
  echo -e "${RED}Error: no existe $CONFIG_FILE${NC}"
  exit 1
fi

read_cfg() {
  python3 -c "import json; print(json.load(open('$CONFIG_FILE'))$1)"
}

PROJECT_ID=$(read_cfg "['gcp']['project_id']")
REGION=$(read_cfg "['gcp']['region']")
JOB_NAME=$(read_cfg "['gcp']['cloud_run_job_name']")
SERVICE_ACCOUNT=$(read_cfg "['gcp']['service_account_email']")
SCHEDULER_NAME=$(read_cfg "['gcp'].get('scheduler_name', '${JOB_NAME}-scheduler')")
SCHEDULE=$(read_cfg "['gcp'].get('schedule', '0 * * * *')")
TIMEZONE=$(read_cfg "['gcp'].get('schedule_timezone', 'America/Lima')")

RUN_URI="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB_NAME}:run"

echo -e "${YELLOW}Proyecto:${NC} $PROJECT_ID"
echo -e "${YELLOW}Job:${NC} $JOB_NAME"
echo -e "${YELLOW}Scheduler:${NC} $SCHEDULER_NAME"
echo -e "${YELLOW}Cron:${NC} $SCHEDULE ($TIMEZONE)"
echo ""

gcloud config set project "$PROJECT_ID"

echo -e "${YELLOW}Habilitando APIs...${NC}"
gcloud services enable cloudscheduler.googleapis.com run.googleapis.com

echo -e "${YELLOW}Permiso run.invoker para la cuenta de servicio...${NC}"
gcloud run jobs add-iam-policy-binding "$JOB_NAME" \
  --region="$REGION" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/run.invoker" \
  --quiet

if gcloud scheduler jobs describe "$SCHEDULER_NAME" --location="$REGION" &>/dev/null; then
  echo -e "${YELLOW}Actualizando scheduler existente...${NC}"
  gcloud scheduler jobs update http "$SCHEDULER_NAME" \
    --location="$REGION" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIMEZONE" \
    --uri="$RUN_URI" \
    --http-method=POST \
    --oauth-service-account-email="$SERVICE_ACCOUNT" \
    --attempt-deadline=900s \
    --description="Micro-batch S3 -> GCS cada hora"
else
  echo -e "${YELLOW}Creando scheduler...${NC}"
  gcloud scheduler jobs create http "$SCHEDULER_NAME" \
    --location="$REGION" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIMEZONE" \
    --uri="$RUN_URI" \
    --http-method=POST \
    --oauth-service-account-email="$SERVICE_ACCOUNT" \
    --attempt-deadline=900s \
    --max-retry-attempts=3 \
    --min-backoff=30s \
    --max-backoff=300s \
    --description="Micro-batch S3 -> GCS cada hora"
fi

echo -e "${GREEN}Scheduler configurado${NC}"
echo ""
echo "Probar ahora:"
echo "  gcloud scheduler jobs run $SCHEDULER_NAME --location=$REGION"
echo ""
echo "Ver ejecuciones del job:"
echo "  gcloud run jobs executions list --job=$JOB_NAME --region=$REGION"
