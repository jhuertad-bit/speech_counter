#!/usr/bin/env bash
# Deploy Cloud Run Job Promotores GCS→GCS (prepare / worker).
set -euo pipefail

missing=0
require() {
  local name="$1"
  local value="$2"
  if [[ -z "${value}" ]]; then
    echo "ERROR: falta ${name} — Variables de sustitución del activador Cloud Build." >&2
    missing=1
  else
    echo "OK ${name}=${value}"
  fi
}

trim() { local v="${1:-}"; v="${v#"${v%%[![:space:]]*}"}"; v="${v%"${v##*[![:space:]]}"}"; printf '%s' "$v"; }

_PROJECT_ID="$(trim "${_PROJECT_ID:-}")"
_JOB_NAME="$(trim "${_JOB_NAME:-}")"
_SERVICE_ACCOUNT="$(trim "${_SERVICE_ACCOUNT:-}")"
_DEST_BUCKET_NAME="$(trim "${_DEST_BUCKET_NAME:-${_BUCKET_NAME:-}}")"
_SOURCE_PROJECT_ID="$(trim "${_SOURCE_PROJECT_ID:-}")"
_SOURCE_BUCKET_NAME="$(trim "${_SOURCE_BUCKET_NAME:-}")"
_SOURCE_PREFIX="$(trim "${_SOURCE_PREFIX:-}")"
_DEST_PREFIX="$(trim "${_DEST_PREFIX:-}")"
_LOCATION="$(trim "${_LOCATION:-}")"
_SOURCE_DIR="$(trim "${_SOURCE_DIR:-}")"
_MEMORY="$(trim "${_MEMORY:-}")"
_CPU="$(trim "${_CPU:-}")"
_TASK_TIMEOUT="$(trim "${_TASK_TIMEOUT:-}")"
_MAX_RETRIES="$(trim "${_MAX_RETRIES:-}")"
_PARALLELISM="$(trim "${_PARALLELISM:-}")"
_CONFIG_PATH="$(trim "${_CONFIG_PATH:-}")"

echo "=== Validando variables del activador ==="
require "_PROJECT_ID" "${_PROJECT_ID}"
require "_JOB_NAME" "${_JOB_NAME}"
require "_SERVICE_ACCOUNT" "${_SERVICE_ACCOUNT}"
require "_DEST_BUCKET_NAME" "${_DEST_BUCKET_NAME}"
require "_SOURCE_PROJECT_ID" "${_SOURCE_PROJECT_ID}"
require "_SOURCE_BUCKET_NAME" "${_SOURCE_BUCKET_NAME}"
if [[ -n "${_SERVICE_ACCOUNT}" && "${_SERVICE_ACCOUNT}" != *"@"* ]]; then
  echo "ERROR: _SERVICE_ACCOUNT debe ser email completo" >&2
  missing=1
fi
if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

SOURCE_DIR="${_SOURCE_DIR:-promotores_gcs_copy/src}"
TASK_TIMEOUT="${_TASK_TIMEOUT:-3600s}"
MAX_RETRIES="${_MAX_RETRIES:-1}"
PARALLELISM="${_PARALLELISM:-10}"
CONFIG_PATH="${_CONFIG_PATH:-/app/config/config.json}"
MEMORY="${_MEMORY:-1Gi}"
CPU="${_CPU:-1}"
LOCATION="${_LOCATION:-us-central1}"

if [[ ! -f "${SOURCE_DIR}/Dockerfile" ]]; then
  echo "ERROR: falta Dockerfile en ${SOURCE_DIR}" >&2
  exit 1
fi

ENV_VARS="CONFIG_PATH=${CONFIG_PATH},PYTHONUNBUFFERED=1"
ENV_VARS+=",GCP_PROJECT_ID=${_PROJECT_ID}"
ENV_VARS+=",DEST_PROJECT_ID=${_PROJECT_ID}"
ENV_VARS+=",DEST_BUCKET_NAME=${_DEST_BUCKET_NAME}"
ENV_VARS+=",GCP_BUCKET_NAME=${_DEST_BUCKET_NAME}"
ENV_VARS+=",GCP_REGION=${LOCATION}"
ENV_VARS+=",GCP_JOB_NAME=${_JOB_NAME}"
ENV_VARS+=",GCP_SERVICE_ACCOUNT_EMAIL=${_SERVICE_ACCOUNT}"
ENV_VARS+=",SOURCE_PROJECT_ID=${_SOURCE_PROJECT_ID}"
ENV_VARS+=",SOURCE_BUCKET_NAME=${_SOURCE_BUCKET_NAME}"
if [[ -n "${_SOURCE_PREFIX}" ]]; then
  ENV_VARS+=",SOURCE_PREFIX=${_SOURCE_PREFIX}"
fi
if [[ -n "${_DEST_PREFIX}" ]]; then
  ENV_VARS+=",DEST_PREFIX=${_DEST_PREFIX}"
fi

echo "IAM origen: con JSON en Secret Manager no hace falta objectViewer a genesys."
echo "IAM BigQuery: dataEditor en raw_cita_promotor + jobUser en el proyecto para ${_SERVICE_ACCOUNT}"

gcloud services enable run.googleapis.com cloudbuild.googleapis.com storage.googleapis.com \
  secretmanager.googleapis.com bigquery.googleapis.com \
  --project="${_PROJECT_ID}" --quiet

if gcloud storage buckets describe "gs://${_DEST_BUCKET_NAME}" --project="${_PROJECT_ID}" &>/dev/null; then
  echo "OK bucket destino gs://${_DEST_BUCKET_NAME}"
else
  echo "Creando bucket destino gs://${_DEST_BUCKET_NAME}..."
  gcloud storage buckets create "gs://${_DEST_BUCKET_NAME}" \
    --project="${_PROJECT_ID}" \
    --location="${LOCATION}" \
    --uniform-bucket-level-access
fi

gcloud storage buckets add-iam-policy-binding "gs://${_DEST_BUCKET_NAME}" \
  --member="serviceAccount:${_SERVICE_ACCOUNT}" \
  --role="roles/storage.objectAdmin" \
  --quiet

# shellcheck disable=SC2088
echo "=== gcloud run jobs deploy ${_JOB_NAME} ==="
gcloud run jobs deploy "${_JOB_NAME}" \
  --project="${_PROJECT_ID}" \
  --region="${LOCATION}" \
  --source="${SOURCE_DIR}" \
  --service-account="${_SERVICE_ACCOUNT}" \
  --set-env-vars="${ENV_VARS}" \
  --memory="${MEMORY}" \
  --cpu="${CPU}" \
  --max-retries="${MAX_RETRIES}" \
  --task-timeout="${TASK_TIMEOUT}" \
  --parallelism="${PARALLELISM}" \
  --tasks=1

echo "=== Deploy OK ==="
echo "Prepare:"
echo "  gcloud run jobs execute ${_JOB_NAME} --region=${LOCATION} --project=${_PROJECT_ID} \\"
echo "    --tasks=1 --update-env-vars=JOB_ROLE=prepare,SYNC_PROCESS_DATE=YYYY-MM-DD"
echo "Worker (N = count del manifiesto):"
echo "  gcloud run jobs execute ${_JOB_NAME} --region=${LOCATION} --project=${_PROJECT_ID} \\"
echo "    --tasks=N --update-env-vars=JOB_ROLE=worker,SYNC_PROCESS_DATE=YYYY-MM-DD"
