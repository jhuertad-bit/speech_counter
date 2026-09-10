#!/bin/bash
# Deploy local del Cloud Run Job (desde mentores_gcs_copy/src).
set -euo pipefail

CONFIG_FILE="config/config.json"
if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Error: no existe $CONFIG_FILE"
  exit 1
fi

read_json() {
  python3 -c "import json; print(json.load(open('$CONFIG_FILE'))$1)"
}

PROJECT_ID="${GCP_PROJECT_ID:-$(read_json "['dest']['project_id']")}"
REGION="${GCP_REGION:-$(read_json "['dest']['region']")}"
JOB_NAME="${GCP_JOB_NAME:-$(read_json "['dest']['cloud_run_job_name']")}"
SERVICE_ACCOUNT="${GCP_SERVICE_ACCOUNT_EMAIL:-$(read_json "['dest']['service_account_email']")}"
DEST_BUCKET="${DEST_BUCKET_NAME:-$(read_json "['dest']['bucket_name']")}"
SOURCE_PROJECT="${SOURCE_PROJECT_ID:-$(read_json "['source']['project_id']")}"
SOURCE_BUCKET="${SOURCE_BUCKET_NAME:-$(read_json "['source']['bucket_name']")}"
SOURCE_PREFIX="${SOURCE_PREFIX:-$(read_json "['source'].get('prefix','')")}"
DEST_PREFIX="${DEST_PREFIX:-$(read_json "['dest'].get('destination_prefix','')")}"

ENV_VARS="CONFIG_PATH=/app/config/config.json,PYTHONUNBUFFERED=1"
ENV_VARS+=",GCP_PROJECT_ID=${PROJECT_ID}"
ENV_VARS+=",DEST_PROJECT_ID=${PROJECT_ID}"
ENV_VARS+=",DEST_BUCKET_NAME=${DEST_BUCKET}"
ENV_VARS+=",GCP_BUCKET_NAME=${DEST_BUCKET}"
ENV_VARS+=",GCP_REGION=${REGION}"
ENV_VARS+=",GCP_JOB_NAME=${JOB_NAME}"
ENV_VARS+=",GCP_SERVICE_ACCOUNT_EMAIL=${SERVICE_ACCOUNT}"
ENV_VARS+=",SOURCE_PROJECT_ID=${SOURCE_PROJECT}"
ENV_VARS+=",SOURCE_BUCKET_NAME=${SOURCE_BUCKET}"
ENV_VARS+=",SOURCE_PREFIX=${SOURCE_PREFIX}"
ENV_VARS+=",DEST_PREFIX=${DEST_PREFIX}"

echo "Proyecto job: $PROJECT_ID"
echo "Job: $JOB_NAME"
echo "SRC: gs://${SOURCE_BUCKET} (${SOURCE_PROJECT})"
echo "DST: gs://${DEST_BUCKET}"

gcloud config set project "$PROJECT_ID"
gcloud run jobs deploy "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --source="." \
  --service-account="$SERVICE_ACCOUNT" \
  --set-env-vars="$ENV_VARS" \
  --memory=1Gi \
  --cpu=1 \
  --max-retries=1 \
  --task-timeout=3600s \
  --parallelism=10 \
  --tasks=1

echo "OK. Preferible orquestar con Cloud Workflows (prepare + worker)."
