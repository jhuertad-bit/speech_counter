#!/usr/bin/env bash
# Deploy Cloud Run Job onemarketer_api_backfill (imagen ya buildeada/pusheada).
# OAuth: _OAUTH_SECRET O bien _OAUTH_USER + _OAUTH_PASSWORD (si no pueden crear secretos).
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
_BUCKET_NAME="$(trim "${_BUCKET_NAME:-}")"
_DATASET_ID="$(trim "${_DATASET_ID:-}")"
_OAUTH_SECRET="$(trim "${_OAUTH_SECRET:-}")"
_OAUTH_USER="$(trim "${_OAUTH_USER:-}")"
_OAUTH_PASSWORD="$(trim "${_OAUTH_PASSWORD:-}")"
_IMAGE="$(trim "${_IMAGE:-}")"
_LOCATION="$(trim "${_LOCATION:-}")"
_MEMORY="$(trim "${_MEMORY:-}")"
_CPU="$(trim "${_CPU:-}")"
_TASK_TIMEOUT="$(trim "${_TASK_TIMEOUT:-}")"
_MAX_RETRIES="$(trim "${_MAX_RETRIES:-}")"
_BACKFILL_START_DATE="$(trim "${_BACKFILL_START_DATE:-}")"
_BACKFILL_END_DATE="$(trim "${_BACKFILL_END_DATE:-}")"
_BACKFILL_TABLES="$(trim "${_BACKFILL_TABLES:-}")"

echo "=== Validando variables del activador ==="
require "_PROJECT_ID" "${_PROJECT_ID}"
require "_JOB_NAME" "${_JOB_NAME}"
require "_SERVICE_ACCOUNT" "${_SERVICE_ACCOUNT}"
require "_BUCKET_NAME" "${_BUCKET_NAME}"
require "_DATASET_ID" "${_DATASET_ID}"
require "_IMAGE" "${_IMAGE}"
if [[ -n "${_SERVICE_ACCOUNT}" && "${_SERVICE_ACCOUNT}" != *"@"* ]]; then
  echo "ERROR: _SERVICE_ACCOUNT debe ser email completo" >&2
  missing=1
fi

if [[ -n "${_OAUTH_SECRET}" ]]; then
  echo "OK _OAUTH_SECRET=${_OAUTH_SECRET}"
elif [[ -n "${_OAUTH_USER}" && -n "${_OAUTH_PASSWORD}" ]]; then
  echo "OK _OAUTH_USER=${_OAUTH_USER} (password via env, sin Secret Manager)"
else
  echo "ERROR: configura _OAUTH_SECRET O bien (_OAUTH_USER + _OAUTH_PASSWORD)." >&2
  missing=1
fi

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

LOCATION="${_LOCATION:-us-central1}"
MEMORY="${_MEMORY:-1Gi}"
CPU="${_CPU:-1}"
TASK_TIMEOUT="${_TASK_TIMEOUT:-86400s}"
MAX_RETRIES="${_MAX_RETRIES:-1}"
BACKFILL_START_DATE="${_BACKFILL_START_DATE:-2026-06-29}"
BACKFILL_TABLES="${_BACKFILL_TABLES:-reporteAtenciones}"

ENV_VARS="PYTHONUNBUFFERED=1"
ENV_VARS+=",GCP_PROJECT_ID=${_PROJECT_ID}"
ENV_VARS+=",GCP_BUCKET_NAME=${_BUCKET_NAME}"
ENV_VARS+=",GCP_DATASET_ID=${_DATASET_ID}"
ENV_VARS+=",GCP_REGION=${LOCATION}"
ENV_VARS+=",GCP_JOB_NAME=${_JOB_NAME}"
ENV_VARS+=",GCP_SERVICE_ACCOUNT_EMAIL=${_SERVICE_ACCOUNT}"
ENV_VARS+=",BACKFILL_START_DATE=${BACKFILL_START_DATE}"
ENV_VARS+=",BACKFILL_TABLES=${BACKFILL_TABLES}"
ENV_VARS+=",STOP_ON_ERROR=0"
if [[ -n "${_BACKFILL_END_DATE}" ]]; then
  ENV_VARS+=",BACKFILL_END_DATE=${_BACKFILL_END_DATE}"
fi
if [[ -z "${_OAUTH_SECRET}" ]]; then
  ENV_VARS+=",ONEMARKETER_OAUTH_USER=${_OAUTH_USER}"
  ENV_VARS+=",ONEMARKETER_OAUTH_PASSWORD=${_OAUTH_PASSWORD}"
fi

echo "=== Habilitando APIs ==="
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  bigquery.googleapis.com storage.googleapis.com \
  --project="${_PROJECT_ID}" --quiet

DEPLOY_ARGS=(
  run jobs deploy "${_JOB_NAME}"
  --project="${_PROJECT_ID}"
  --region="${LOCATION}"
  --image="${_IMAGE}"
  --service-account="${_SERVICE_ACCOUNT}"
  --set-env-vars="${ENV_VARS}"
  --memory="${MEMORY}"
  --cpu="${CPU}"
  --max-retries="${MAX_RETRIES}"
  --task-timeout="${TASK_TIMEOUT}"
  --parallelism=1
  --tasks=1
)

if [[ -n "${_OAUTH_SECRET}" ]]; then
  DEPLOY_ARGS+=(--set-secrets="ONEMARKETER_API_CREDENTIALS=${_OAUTH_SECRET}:latest")
fi

echo "=== gcloud run jobs deploy ${_JOB_NAME} ==="
echo "Imagen: ${_IMAGE}"
gcloud "${DEPLOY_ARGS[@]}"

echo "=== Deploy OK ==="
echo "Ejecutar:"
echo "  gcloud run jobs execute ${_JOB_NAME} --region=${LOCATION} --project=${_PROJECT_ID} --tasks=1"
echo "Rango custom:"
echo "  gcloud run jobs execute ${_JOB_NAME} --region=${LOCATION} --project=${_PROJECT_ID} --tasks=1 \\"
echo "    --update-env-vars=BACKFILL_START_DATE=2026-06-29,BACKFILL_END_DATE=2026-07-15,BACKFILL_TABLES=reporteAtenciones"
