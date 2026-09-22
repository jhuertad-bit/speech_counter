#!/usr/bin/env bash
# ============================================================
# deploy.sh — Cloud Run Job: cr_serialize_queuesmart (GPU L4)
#
# Preferible: activador Cloud Build con cr_serialize_queuesmart/cloudbuild.yaml
# Este script lanza el mismo config desde la raíz del monorepo.
#
# Uso:
#   bash cr_serialize_queuesmart/deploy.sh
# ============================================================

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG_FILE="$(dirname "$0")/src/config/config.json"

PROJECT_ID=$(jq -r '.gcp.project_id' "$CONFIG_FILE")
JOB_NAME=$(jq -r '.gcp.cloud_run_job_name' "$CONFIG_FILE")
SA_EMAIL=$(jq -r '.gcp.service_account_email' "$CONFIG_FILE")
BUCKET=$(jq -r '.gcp.bucket_audio' "$CONFIG_FILE")

echo "=== Cloud Build GPU (queuesmart) project=${PROJECT_ID} job=${JOB_NAME} ==="
cd "${ROOT}"
gcloud builds submit \
  --project="${PROJECT_ID}" \
  --config=cr_serialize_queuesmart/cloudbuild.yaml \
  --substitutions="_PROJECT_ID=${PROJECT_ID},_JOB_NAME=${JOB_NAME},_SERVICE_ACCOUNT=${SA_EMAIL},_BUCKET_NAME=${BUCKET}" \
  .

echo "OK. Ejecutar:"
echo "  gcloud run jobs execute ${JOB_NAME} --region=us-central1 --project=${PROJECT_ID} --update-env-vars=FECHA_AUDIO=YYYY-MM-DD"
