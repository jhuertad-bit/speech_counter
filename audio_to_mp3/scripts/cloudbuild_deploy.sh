#!/usr/bin/env bash
# Deploy Cloud Function Gen2 (GCS trigger) con Dockerfile (ffmpeg).
# Nota: gcloud functions deploy NO soporta --image; usa --source + Dockerfile.
set -euo pipefail

missing=0
require() {
  local name="$1"
  local value="$2"
  if [[ -z "${value}" ]]; then
    echo "ERROR: falta ${name} — agrégala en el activador de Cloud Build." >&2
    missing=1
  else
    echo "OK ${name}=${value}"
  fi
}

echo "=== Validando variables del activador ==="
require "_PROJECT_ID" "${_PROJECT_ID:-}"
require "_FUNCTION_NAME" "${_FUNCTION_NAME:-}"
require "_SERVICE_ACCOUNT" "${_SERVICE_ACCOUNT:-}"
require "_BUCKET_NAME" "${_BUCKET_NAME:-}"

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

LOCATION="${_LOCATION:-us-central1}"
REPO_NAME="${_REPO_NAME:-gcf-artifacts}"
RUNTIME="${_RUNTIME:-python310}"
CONFIG_PATH="${_CONFIG_PATH:-config/config.json}"
MEMORY="${_MEMORY:-6144MB}"
TIMEOUT="${_TIMEOUT:-540s}"
MAX_INSTANCES="${_MAX_INSTANCES:-30}"
CONCURRENCY="${_CONCURRENCY:-1}"
SOURCE_DIR="${_SOURCE_DIR:-audio_to_mp3}"

echo "=== gcloud functions deploy ${_FUNCTION_NAME} (source: ${SOURCE_DIR}/ + Dockerfile) ==="
gcloud functions deploy "${_FUNCTION_NAME}" \
  --gen2 \
  --project="${_PROJECT_ID}" \
  --region="${LOCATION}" \
  --runtime="${RUNTIME}" \
  --source="${SOURCE_DIR}" \
  --entry-point=audio_to_mp3_converter \
  --docker-repository="${LOCATION}-docker.pkg.dev/${_PROJECT_ID}/${REPO_NAME}" \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=${_BUCKET_NAME}" \
  --trigger-location="${LOCATION}" \
  --service-account="${_SERVICE_ACCOUNT}" \
  --memory="${MEMORY}" \
  --timeout="${TIMEOUT}" \
  --max-instances="${MAX_INSTANCES}" \
  --concurrency="${CONCURRENCY}" \
  --set-env-vars="CONFIG_PATH=${CONFIG_PATH},GCP_PROJECT_ID=${_PROJECT_ID},GCP_BUCKET_NAME=${_BUCKET_NAME},GCP_REGION=${LOCATION},GCP_FUNCTION_NAME=${_FUNCTION_NAME},GCP_SERVICE_ACCOUNT_EMAIL=${_SERVICE_ACCOUNT}"

echo "Función desplegada. Trigger: gs://${_BUCKET_NAME} (object.finalized)"
