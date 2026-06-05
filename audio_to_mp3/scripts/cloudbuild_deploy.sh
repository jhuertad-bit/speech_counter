#!/usr/bin/env bash
# Deploy Cloud Function Gen2 (GCS trigger) con imagen custom (ffmpeg).
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
IMAGE_NAME="${_IMAGE_NAME:-audio-to-mp3}"
COMMIT_SHA="${COMMIT_SHA:-latest}"
CONFIG_PATH="${_CONFIG_PATH:-config/config.json}"
MEMORY="${_MEMORY:-6144MB}"
TIMEOUT="${_TIMEOUT:-540s}"
MAX_INSTANCES="${_MAX_INSTANCES:-30}"
CONCURRENCY="${_CONCURRENCY:-1}"

IMAGE="${LOCATION}-docker.pkg.dev/${_PROJECT_ID}/${REPO_NAME}/${IMAGE_NAME}:${COMMIT_SHA}"

echo "=== gcloud functions deploy ${_FUNCTION_NAME} (imagen: ${IMAGE}) ==="
gcloud functions deploy "${_FUNCTION_NAME}" \
  --gen2 \
  --project="${_PROJECT_ID}" \
  --region="${LOCATION}" \
  --image="${IMAGE}" \
  --entry-point=audio_to_mp3_converter \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=${_BUCKET_NAME}" \
  --trigger-location="${LOCATION}" \
  --service-account="${_SERVICE_ACCOUNT}" \
  --memory="${MEMORY}" \
  --timeout="${TIMEOUT}" \
  --max-instances="${MAX_INSTANCES}" \
  --concurrency="${CONCURRENCY}" \
  --set-env-vars="CONFIG_PATH=${CONFIG_PATH}"

echo "Función desplegada. Trigger: gs://${_BUCKET_NAME} (object.finalized)"
