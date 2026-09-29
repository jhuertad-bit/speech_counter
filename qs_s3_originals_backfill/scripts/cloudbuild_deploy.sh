#!/usr/bin/env bash
# Deploy Cloud Run Job: backfill originales S3 → GCS + UPDATE BQ.
set -euo pipefail

missing=0
require() {
  local name="$1"
  local value="$2"
  local mask="${3:-false}"
  if [[ -z "${value}" ]]; then
    echo "ERROR: falta ${name} — Variables de sustitución del activador Cloud Build." >&2
    missing=1
  else
    if [[ "${mask}" == "true" ]]; then
      echo "OK ${name}=***"
    else
      echo "OK ${name}=${value}"
    fi
  fi
}

trim() { local v="${1:-}"; v="${v#"${v%%[![:space:]]*}"}"; v="${v%"${v##*[![:space:]]}"}"; printf '%s' "$v"; }

_PROJECT_ID="$(trim "${_PROJECT_ID:-}")"
_JOB_NAME="$(trim "${_JOB_NAME:-}")"
_SERVICE_ACCOUNT="$(trim "${_SERVICE_ACCOUNT:-}")"
_BUCKET_NAME="$(trim "${_BUCKET_NAME:-}")"
_DATASET_ID="$(trim "${_DATASET_ID:-}")"
_BQ_TABLE_ID="$(trim "${_BQ_TABLE_ID:-}")"
_AWS_S3_BUCKET="$(trim "${_AWS_S3_BUCKET:-}")"
_AWS_S3_PREFIX="$(trim "${_AWS_S3_PREFIX:-}")"
_AWS_ENDPOINT_URL="$(trim "${_AWS_ENDPOINT_URL:-}")"
_GCP_DESTINATION_PREFIX="$(trim "${_GCP_DESTINATION_PREFIX:-}")"
_LOCATION="$(trim "${_LOCATION:-}")"
_SOURCE_DIR="$(trim "${_SOURCE_DIR:-}")"
_MEMORY="$(trim "${_MEMORY:-}")"
_CPU="$(trim "${_CPU:-}")"
_TASK_TIMEOUT="$(trim "${_TASK_TIMEOUT:-}")"
_MAX_RETRIES="$(trim "${_MAX_RETRIES:-}")"
_PARALLELISM="$(trim "${_PARALLELISM:-}")"
_CONFIG_PATH="$(trim "${_CONFIG_PATH:-}")"
_AWS_ACCESS_KEY_ID="$(trim "${_AWS_ACCESS_KEY_ID:-}")"
_AWS_SECRET_ACCESS_KEY="$(trim "${_AWS_SECRET_ACCESS_KEY:-}")"

echo "=== Validando variables del activador ==="
require "_PROJECT_ID" "${_PROJECT_ID}"
require "_JOB_NAME" "${_JOB_NAME}"
require "_SERVICE_ACCOUNT" "${_SERVICE_ACCOUNT}"
require "_BUCKET_NAME" "${_BUCKET_NAME}"
require "_DATASET_ID" "${_DATASET_ID}"
require "_AWS_ACCESS_KEY_ID" "${_AWS_ACCESS_KEY_ID}"
require "_AWS_SECRET_ACCESS_KEY" "${_AWS_SECRET_ACCESS_KEY}" "true"
if [[ -n "${_SERVICE_ACCOUNT}" && "${_SERVICE_ACCOUNT}" != *"@"* ]]; then
  echo "ERROR: _SERVICE_ACCOUNT debe ser email completo" >&2
  missing=1
fi
if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

SOURCE_DIR="${_SOURCE_DIR:-qs_s3_originals_backfill/src}"
TASK_TIMEOUT="${_TASK_TIMEOUT:-3600s}"
MAX_RETRIES="${_MAX_RETRIES:-1}"
PARALLELISM="${_PARALLELISM:-20}"
CONFIG_PATH="${_CONFIG_PATH:-/app/config/config.json}"
MEMORY="${_MEMORY:-1Gi}"
CPU="${_CPU:-1}"
LOCATION="${_LOCATION:-us-central1}"
BQ_TABLE_ID="${_BQ_TABLE_ID:-hist_queesmart_mp3_catalog}"

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "ERROR: no existe directorio fuente ${SOURCE_DIR}" >&2
  exit 1
fi
if [[ ! -f "${SOURCE_DIR}/Dockerfile" ]]; then
  echo "ERROR: falta Dockerfile en ${SOURCE_DIR}" >&2
  exit 1
fi

ENV_VARS="CONFIG_PATH=${CONFIG_PATH},PYTHONUNBUFFERED=1"
ENV_VARS+=",GCP_PROJECT_ID=${_PROJECT_ID}"
ENV_VARS+=",GCP_BUCKET_NAME=${_BUCKET_NAME}"
ENV_VARS+=",GCP_DATASET_ID=${_DATASET_ID}"
ENV_VARS+=",GCP_BQ_TABLE_ID=${BQ_TABLE_ID}"
ENV_VARS+=",GCP_REGION=${LOCATION}"
ENV_VARS+=",GCP_JOB_NAME=${_JOB_NAME}"
ENV_VARS+=",GCP_SERVICE_ACCOUNT_EMAIL=${_SERVICE_ACCOUNT}"
if [[ -n "${_GCP_DESTINATION_PREFIX:-}" ]]; then
  ENV_VARS+=",GCP_DESTINATION_PREFIX=${_GCP_DESTINATION_PREFIX}"
fi
if [[ -n "${_AWS_S3_BUCKET:-}" ]]; then
  ENV_VARS+=",AWS_S3_BUCKET=${_AWS_S3_BUCKET}"
  ENV_VARS+=",AWS_REGION=us-east-1"
fi
if [[ -n "${_AWS_S3_PREFIX:-}" ]]; then
  ENV_VARS+=",AWS_S3_PREFIX=${_AWS_S3_PREFIX}"
fi
if [[ -n "${_AWS_ENDPOINT_URL:-}" ]]; then
  ENV_VARS+=",AWS_ENDPOINT_URL=${_AWS_ENDPOINT_URL}"
fi
ENV_VARS+=",AWS_ACCESS_KEY_ID=${_AWS_ACCESS_KEY_ID}"
ENV_VARS+=",AWS_SECRET_ACCESS_KEY=${_AWS_SECRET_ACCESS_KEY}"

echo "=== Habilitando APIs ==="
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  secretmanager.googleapis.com bigquery.googleapis.com storage.googleapis.com \
  --project="${_PROJECT_ID}" --quiet

echo "=== Bucket destino GCS: gs://${_BUCKET_NAME} ==="
if gcloud storage buckets describe "gs://${_BUCKET_NAME}" --project="${_PROJECT_ID}" &>/dev/null; then
  echo "OK bucket ya existe"
else
  gcloud storage buckets create "gs://${_BUCKET_NAME}" \
    --project="${_PROJECT_ID}" \
    --location="${LOCATION}" \
    --uniform-bucket-level-access
fi
gcloud storage buckets add-iam-policy-binding "gs://${_BUCKET_NAME}" \
  --member="serviceAccount:${_SERVICE_ACCOUNT}" \
  --role="roles/storage.objectAdmin" \
  --quiet

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
echo "1) ALTER columnas (si aún no): qs_s3_to_gcs/bigquery/sqls/alter_gcs_original_path.sql"
echo "2) Prepare (ejemplo 2 meses):"
echo "  gcloud run jobs execute ${_JOB_NAME} --region=${LOCATION} --project=${_PROJECT_ID} \\"
echo "    --tasks=1 --update-env-vars=JOB_ROLE=prepare,BACKFILL_START_DATE=2026-07-01,BACKFILL_END_DATE=2026-08-31"
echo "3) Worker (N = count del .meta.json):"
echo "  gcloud run jobs execute ${_JOB_NAME} --region=${LOCATION} --project=${_PROJECT_ID} \\"
echo "    --tasks=N --update-env-vars=JOB_ROLE=worker,BACKFILL_START_DATE=2026-07-01,BACKFILL_END_DATE=2026-08-31"
echo "Manifiesto: gs://${_BUCKET_NAME}/state/manifests_originals_backfill/{start}_{end}.meta.json"
