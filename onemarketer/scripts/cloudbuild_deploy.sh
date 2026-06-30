#!/usr/bin/env bash
# Deploy Cloud Function Gen2 con Dockerfile (ffmpeg + ETL OneMarketer).
# Nota: gcloud functions deploy NO soporta --image; usa --source + Dockerfile.
set -euo pipefail

missing=0
require() {
  local name="$1"
  local value="$2"
  if [[ -z "${value}" ]]; then
    echo "ERROR: falta ${name} — agrégala en el activador de Cloud Build (Variables de sustitución)." >&2
    missing=1
  else
    echo "OK ${name}=${value}"
  fi
}

echo "=== Validando variables del activador ==="
require "_PROJECT_ID" "${_PROJECT_ID:-}"
require "_FUNCTION_NAME" "${_FUNCTION_NAME:-}"
require "_SERVICE_ACCOUNT" "${_SERVICE_ACCOUNT:-}"
if [[ -n "${_SERVICE_ACCOUNT:-}" && "${_SERVICE_ACCOUNT}" != *"@"* ]]; then
  echo "ERROR: _SERVICE_ACCOUNT debe ser email completo (ej. nombre@${_PROJECT_ID}.iam.gserviceaccount.com), no '${_SERVICE_ACCOUNT}'" >&2
  missing=1
fi
require "_BUCKET_NAME" "${_BUCKET_NAME:-}"
require "_DATASET_ID" "${_DATASET_ID:-}"
require "_SCHEDULER_NAME" "${_SCHEDULER_NAME:-}"
require "_SERVICE_ACCOUNT_NAME" "${_SERVICE_ACCOUNT_NAME:-}"

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

LOCATION="${_LOCATION:-us-central1}"
REPO_NAME="${_REPO_NAME:-gcf-artifacts}"
ENTRY_POINT="${_ENTRY_POINT:-main}"
RUNTIME="${_RUNTIME:-python310}"
MEMORY="${_MEMORY:-2Gi}"
TIMEOUT="${_TIMEOUT:-3600s}"
CPU="${_CPU:-2}"
MAX_INSTANCES="${_MAX_INSTANCES:-3}"
CONCURRENCY="${_CONCURRENCY:-1}"
ALLOW_UNAUTH="${_ALLOW_UNAUTHENTICATED:-false}"
SOURCE_DIR="${_SOURCE_DIR:-onemarketer/src}"

ENV_VARS="GCP_PROJECT_ID=${_PROJECT_ID},GCP_BUCKET_NAME=${_BUCKET_NAME},GCP_DATASET_ID=${_DATASET_ID},GCP_REGION=${LOCATION},GCP_FUNCTION_NAME=${_FUNCTION_NAME},GCP_SCHEDULER_NAME=${_SCHEDULER_NAME},GCP_SERVICE_ACCOUNT_NAME=${_SERVICE_ACCOUNT_NAME}"

# Prod: carpeta reportechats (minúsculas). Dev: omitir → config.json reporteChats.
if [[ -n "${_GCS_PATH:-}" ]]; then
  ENV_VARS="${ENV_VARS},GCP_GCS_PATH=${_GCS_PATH}"
  echo "OK _GCS_PATH=${_GCS_PATH} → GCP_GCS_PATH"
fi

DEPLOY_ARGS=(
  functions deploy "${_FUNCTION_NAME}"
  --gen2
  --project="${_PROJECT_ID}"
  --region="${LOCATION}"
  --runtime="${RUNTIME}"
  --source="${SOURCE_DIR}"
  --entry-point="${ENTRY_POINT}"
  --trigger-http
  --memory="${MEMORY}"
  --timeout="${TIMEOUT}"
  --cpu="${CPU}"
  --max-instances="${MAX_INSTANCES}"
  --concurrency="${CONCURRENCY}"
  --service-account="${_SERVICE_ACCOUNT}"
  --set-env-vars="${ENV_VARS}"
)

if [[ -n "${REPO_NAME}" ]]; then
  DEPLOY_ARGS+=(
    "--docker-repository=${LOCATION}-docker.pkg.dev/${_PROJECT_ID}/${REPO_NAME}"
  )
fi

if [[ "${ALLOW_UNAUTH}" == "true" ]]; then
  echo "Modo público: --allow-unauthenticated"
  DEPLOY_ARGS+=(--allow-unauthenticated)
else
  echo "Modo autenticado: Scheduler con OIDC (ver scheduler-setup.sh)"
fi

echo "=== gcloud functions deploy ${_FUNCTION_NAME} (source: ${SOURCE_DIR}/ + Dockerfile) ==="
gcloud services enable vision.googleapis.com --project="${_PROJECT_ID}" --quiet
gcloud "${DEPLOY_ARGS[@]}"
