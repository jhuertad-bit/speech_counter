#!/usr/bin/env bash
# Deploy local: build imagen + ambos Jobs (promotor + mentor).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
CONFIG_FILE="${ROOT}/src/config/config.json"

PROJECT_ID=$(jq -r '.gcp.project_id' "$CONFIG_FILE")
REGION=$(jq -r '.gcp.region' "$CONFIG_FILE")
IMAGE=$(jq -r '.gcp.docker_image_repository' "$CONFIG_FILE")
SA_EMAIL=$(jq -r '.gcp.service_account_email' "$CONFIG_FILE")
WHISPER_MODEL="${WHISPER_MODEL:-turbo}"
DEPLOY_CANALES="${DEPLOY_CANALES:-promotor,mentor}"

echo "=== Build ${IMAGE} ==="
gcloud builds submit "${ROOT}/src" \
  --project="${PROJECT_ID}" \
  --tag="${IMAGE}" \
  --timeout="1800s"

export _PROJECT_ID="${PROJECT_ID}"
export _SERVICE_ACCOUNT="${SA_EMAIL}"
export _LOCATION="${REGION}"
export _IMAGE_NAME="$(basename "${IMAGE}")"
export _IMAGE_TAG="latest"
export _WHISPER_MODEL="${WHISPER_MODEL}"
export _DEPLOY_CANALES="${DEPLOY_CANALES}"
# Force image:latest by tagging path used in cloudbuild_deploy
bash "${ROOT}/scripts/cloudbuild_deploy.sh"

echo ""
echo "OK. Ejemplo:"
echo "  gcloud run jobs execute prd-utpbi-cita-promotor-audio-serialize-whisper \\"
echo "    --region=${REGION} --project=${PROJECT_ID} \\"
echo "    --update-env-vars=FECHA_AUDIO=YYYY-MM-DD"
