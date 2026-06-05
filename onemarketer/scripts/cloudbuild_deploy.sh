#!/usr/bin/env bash
# Deploy Cloud Function Gen2 desde Cloud Build (variables ${_...} sustituidas por el activador).
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
require "_BUCKET_NAME" "${_BUCKET_NAME:-}"
require "_DATASET_ID" "${_DATASET_ID:-}"
require "_SCHEDULER_NAME" "${_SCHEDULER_NAME:-}"
require "_SERVICE_ACCOUNT_NAME" "${_SERVICE_ACCOUNT_NAME:-}"

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

LOCATION="${_LOCATION:-us-central1}"
RUNTIME="${_RUNTIME:-python310}"
ENTRY_POINT="${_ENTRY_POINT:-main}"
MEMORY="${_MEMORY:-2Gi}"
TIMEOUT="${_TIMEOUT:-3600s}"
CPU="${_CPU:-2}"
MAX_INSTANCES="${_MAX_INSTANCES:-3}"
CONCURRENCY="${_CONCURRENCY:-1}"
ALLOW_UNAUTH="${_ALLOW_UNAUTHENTICATED:-false}"

ENV_VARS="GCP_PROJECT_ID=${_PROJECT_ID},GCP_BUCKET_NAME=${_BUCKET_NAME},GCP_DATASET_ID=${_DATASET_ID},GCP_REGION=${LOCATION},GCP_FUNCTION_NAME=${_FUNCTION_NAME},GCP_SCHEDULER_NAME=${_SCHEDULER_NAME},GCP_SERVICE_ACCOUNT_NAME=${_SERVICE_ACCOUNT_NAME}"

DEPLOY_ARGS=(
  functions deploy "${_FUNCTION_NAME}"
  --gen2
  --project="${_PROJECT_ID}"
  --region="${LOCATION}"
  --runtime="${RUNTIME}"
  --source=onemarketer/src
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

if [[ "${ALLOW_UNAUTH}" == "true" ]]; then
  echo "Modo público: --allow-unauthenticated (requiere run.services.setIamPolicy en la SA de Cloud Build)"
  DEPLOY_ARGS+=(--allow-unauthenticated)
else
  echo "Modo autenticado: sin --allow-unauthenticated (Scheduler debe usar OIDC; ver scheduler-setup.sh)"
fi

echo "=== gcloud functions deploy ${_FUNCTION_NAME} ==="
gcloud "${DEPLOY_ARGS[@]}"
