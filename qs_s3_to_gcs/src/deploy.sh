#!/bin/bash
# Despliega Cloud Run Job para micro-batch S3 -> GCS (opcional Scheduler cada hora).

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

PROJECT_ID=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['project_id'])")
REGION=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['region'])")
JOB_NAME=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['cloud_run_job_name'])")
SERVICE_ACCOUNT=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['service_account_email'])")
GCS_BUCKET=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['bucket_name'])")
DATASET_ID=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp'].get('dataset_id') or json.load(open('$CONFIG_FILE'))['bigquery']['dataset_id'])")
SCHEDULER_NAME=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp'].get('scheduler_name', ''))")
CFG_AWS_S3_BUCKET=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['aws']['bucket'])")
CFG_AWS_S3_PREFIX=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['aws'].get('prefix', ''))")
CFG_AWS_ENDPOINT_URL=$(python3 -c "import json; c=json.load(open('$CONFIG_FILE'))['aws']; print(c.get('endpoint_url') or '')")
DEST_PREFIX=$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['gcp']['destination_prefix'])")

# Overrides: prioridad env > config.json (mismo criterio que onemarketer)
PROJECT_ID="${GCP_PROJECT_ID:-$PROJECT_ID}"
REGION="${GCP_REGION:-$REGION}"
JOB_NAME="${GCP_JOB_NAME:-$JOB_NAME}"
SERVICE_ACCOUNT="${GCP_SERVICE_ACCOUNT_EMAIL:-$SERVICE_ACCOUNT}"
GCS_BUCKET="${GCP_BUCKET_NAME:-$GCS_BUCKET}"
DATASET_ID="${GCP_DATASET_ID:-$DATASET_ID}"
SCHEDULER_NAME="${GCP_SCHEDULER_NAME:-$SCHEDULER_NAME}"
AWS_S3_BUCKET="${AWS_S3_BUCKET:-$CFG_AWS_S3_BUCKET}"
AWS_S3_PREFIX="${AWS_S3_PREFIX:-$CFG_AWS_S3_PREFIX}"
AWS_ENDPOINT_URL="${AWS_ENDPOINT_URL:-$CFG_AWS_ENDPOINT_URL}"
DEST_PREFIX="${GCP_DESTINATION_PREFIX:-$DEST_PREFIX}"

GCP_ENV_VARS="CONFIG_PATH=/app/config/config.json,PYTHONUNBUFFERED=1"
GCP_ENV_VARS+=",GCP_PROJECT_ID=${PROJECT_ID}"
GCP_ENV_VARS+=",GCP_BUCKET_NAME=${GCS_BUCKET}"
GCP_ENV_VARS+=",GCP_DATASET_ID=${DATASET_ID}"
GCP_ENV_VARS+=",GCP_REGION=${REGION}"
GCP_ENV_VARS+=",GCP_JOB_NAME=${JOB_NAME}"
GCP_ENV_VARS+=",GCP_SERVICE_ACCOUNT_EMAIL=${SERVICE_ACCOUNT}"
GCP_ENV_VARS+=",GCP_SCHEDULER_NAME=${SCHEDULER_NAME}"
GCP_ENV_VARS+=",GCP_DESTINATION_PREFIX=${DEST_PREFIX}"
GCP_ENV_VARS+=",AWS_S3_BUCKET=${AWS_S3_BUCKET}"
GCP_ENV_VARS+=",AWS_S3_PREFIX=${AWS_S3_PREFIX}"
GCP_ENV_VARS+=",AWS_REGION=us-east-1"
if [[ -n "$AWS_ENDPOINT_URL" && "$AWS_ENDPOINT_URL" != "None" ]]; then
  GCP_ENV_VARS+=",AWS_ENDPOINT_URL=${AWS_ENDPOINT_URL}"
fi
if [[ -n "${AWS_ACCESS_KEY_ID:-}" && -n "${AWS_SECRET_ACCESS_KEY:-}" ]]; then
  GCP_ENV_VARS+=",AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID}"
  GCP_ENV_VARS+=",AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}"
else
  echo -e "${YELLOW}WARN: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY no definidas — ver docs/aws-credentials-env-workaround.md${NC}"
fi
IMAGE="gcr.io/${PROJECT_ID}/${JOB_NAME}:latest"
SCHEDULER_NAME="${JOB_NAME}-scheduler"

echo -e "${YELLOW}Proyecto:${NC} $PROJECT_ID"
echo -e "${YELLOW}Job:${NC} $JOB_NAME"
echo -e "${YELLOW}Imagen:${NC} $IMAGE"
echo ""

gcloud config set project "$PROJECT_ID"

ensure_gcs_bucket() {
  if gcloud storage buckets describe "gs://${GCS_BUCKET}" --project="${PROJECT_ID}" &>/dev/null; then
    echo -e "${GREEN}Bucket ya existe:${NC} gs://${GCS_BUCKET}"
  else
    echo -e "${YELLOW}Creando bucket gs://${GCS_BUCKET} en ${REGION}...${NC}"
    gcloud storage buckets create "gs://${GCS_BUCKET}" \
      --project="${PROJECT_ID}" \
      --location="${REGION}" \
      --uniform-bucket-level-access
  fi
  gcloud storage buckets add-iam-policy-binding "gs://${GCS_BUCKET}" \
    --member="serviceAccount:${SERVICE_ACCOUNT}" \
    --role="roles/storage.objectAdmin" \
    --quiet
}

echo -e "${YELLOW}Verificando bucket destino...${NC}"
ensure_gcs_bucket

echo -e "${YELLOW}Build imagen...${NC}"
gcloud builds submit --tag "$IMAGE" .

echo -e "${YELLOW}Desplegando Cloud Run Job...${NC}"
if gcloud run jobs describe "$JOB_NAME" --region="$REGION" &>/dev/null; then
  gcloud run jobs update "$JOB_NAME" \
    --image="$IMAGE" \
    --region="$REGION" \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="$GCP_ENV_VARS" \
    --memory=512Mi \
    --cpu=1 \
    --max-retries=1 \
    --task-timeout=900s
else
  gcloud run jobs create "$JOB_NAME" \
    --image="$IMAGE" \
    --region="$REGION" \
    --service-account="$SERVICE_ACCOUNT" \
    --set-env-vars="$GCP_ENV_VARS" \
    --memory=512Mi \
    --cpu=1 \
    --max-retries=1 \
    --task-timeout=900s
fi

echo -e "${GREEN}Cloud Run Job listo${NC}"
echo ""
echo -e "${YELLOW}Ejecutar manualmente:${NC}"
echo "  gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo -e "${YELLOW}Programar cada hora (Cloud Scheduler):${NC}"
echo "  ./setup-scheduler.sh"
echo "  (ver README.md sección 'Ejecución cada hora con Cloud Scheduler')"
echo ""
echo -e "${YELLOW}Destino GCS:${NC} gs://$GCS_BUCKET/"
