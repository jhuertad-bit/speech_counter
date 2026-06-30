#!/usr/bin/env bash
# Deploy Cloud Run Job SQL Server → BigQuery.
set -euo pipefail

missing=0
require() {
  local name="$1"
  local value="$2"
  local mask="${3:-false}"
  if [[ -z "${value}" ]]; then
    echo "ERROR: falta ${name} — agrégala en el activador de Cloud Build." >&2
    missing=1
  else
    if [[ "${mask}" == "true" ]]; then
      echo "OK ${name}=***"
    else
      echo "OK ${name}=${value}"
    fi
  fi
}

echo "=== Validando variables del activador ==="
require "_PROJECT_ID" "${_PROJECT_ID:-}"
require "_JOB_NAME" "${_JOB_NAME:-}"
require "_SERVICE_ACCOUNT" "${_SERVICE_ACCOUNT:-}"
require "_DATASET_ID" "${_DATASET_ID:-}"
require "_SQL_SERVER_HOST" "${_SQL_SERVER_HOST:-}"
require "_SQL_SERVER_DATABASE" "${_SQL_SERVER_DATABASE:-}"
require "_SQL_SOURCE_TABLE" "${_SQL_SOURCE_TABLE:-}"
require "_SQL_SERVER_USER" "${_SQL_SERVER_USER:-}"
require "_SQL_SERVER_PASSWORD" "${_SQL_SERVER_PASSWORD:-}" "true"

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

SOURCE_DIR="${_SOURCE_DIR:-qs_sql_to_bq/src}"
MEMORY="${_MEMORY:-512Mi}"
CPU="${_CPU:-1}"
TASK_TIMEOUT="${_TASK_TIMEOUT:-900s}"
MAX_RETRIES="${_MAX_RETRIES:-1}"
CONFIG_PATH="${_CONFIG_PATH:-/app/config/config.json}"
LOCATION="${_LOCATION:-us-central1}"
SCHEDULER_NAME="${_SCHEDULER_NAME:-${_JOB_NAME}-daily}"

ENV_VARS="CONFIG_PATH=${CONFIG_PATH},PYTHONUNBUFFERED=1"
ENV_VARS+=",GCP_PROJECT_ID=${_PROJECT_ID}"
ENV_VARS+=",GCP_DATASET_ID=${_DATASET_ID}"
ENV_VARS+=",GCP_REGION=${LOCATION}"
ENV_VARS+=",GCP_JOB_NAME=${_JOB_NAME}"
ENV_VARS+=",GCP_SERVICE_ACCOUNT_EMAIL=${_SERVICE_ACCOUNT}"
ENV_VARS+=",GCP_SCHEDULER_NAME=${SCHEDULER_NAME}"
ENV_VARS+=",SQL_SERVER_HOST=${_SQL_SERVER_HOST}"
ENV_VARS+=",SQL_SERVER_PORT=${_SQL_SERVER_PORT:-1433}"
ENV_VARS+=",SQL_SERVER_DATABASE=${_SQL_SERVER_DATABASE}"
ENV_VARS+=",SQL_SERVER_SCHEMA=${_SQL_SERVER_SCHEMA:-dbo}"
ENV_VARS+=",SQL_SOURCE_TABLE=${_SQL_SOURCE_TABLE}"
ENV_VARS+=",SQL_SERVER_USER=${_SQL_SERVER_USER}"
ENV_VARS+=",SQL_SERVER_PASSWORD=${_SQL_SERVER_PASSWORD}"
if [[ -n "${_SQL_CUSTOM_QUERY:-}" ]]; then
  ENV_VARS+=",SQL_CUSTOM_QUERY=${_SQL_CUSTOM_QUERY}"
fi
if [[ -n "${_SYNC_MODE:-}" ]]; then
  ENV_VARS+=",SYNC_MODE=${_SYNC_MODE}"
fi

echo "=== Habilitando APIs ==="
gcloud services enable run.googleapis.com cloudbuild.googleapis.com --project="${_PROJECT_ID}" --quiet

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
  --task-timeout="${TASK_TIMEOUT}"

echo "=== Deploy OK ==="
echo "  gcloud run jobs execute ${_JOB_NAME} --region=${LOCATION} --project=${_PROJECT_ID}"
