#!/usr/bin/env bash
# Deploy Cloud Run Job S3 → GCS (micro-batch QuickSight / QueeSmart).
set -euo pipefail

missing=0
require() {
  local name="$1"
  local value="$2"
  local mask="${3:-false}"
  if [[ -z "${value}" ]]; then
    echo "ERROR: falta ${name} — agrégala en el activador de Cloud Build (Variables de sustitución)." >&2
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
require "_BUCKET_NAME" "${_BUCKET_NAME:-}"
require "_DATASET_ID" "${_DATASET_ID:-}"
require "_AWS_ACCESS_KEY_ID" "${_AWS_ACCESS_KEY_ID:-}"
require "_AWS_SECRET_ACCESS_KEY" "${_AWS_SECRET_ACCESS_KEY:-}" "true"
if [[ -n "${_SERVICE_ACCOUNT:-}" && "${_SERVICE_ACCOUNT}" != *"@"* ]]; then
  echo "ERROR: _SERVICE_ACCOUNT debe ser email completo (ej. nombre@${_PROJECT_ID}.iam.gserviceaccount.com), no '${_SERVICE_ACCOUNT}'" >&2
  missing=1
fi

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

SOURCE_DIR="${_SOURCE_DIR:-qs_s3_to_gcs/src}"
MEMORY="${_MEMORY:-512Mi}"
CPU="${_CPU:-1}"
TASK_TIMEOUT="${_TASK_TIMEOUT:-900s}"
MAX_RETRIES="${_MAX_RETRIES:-1}"
CONFIG_PATH="${_CONFIG_PATH:-/app/config/config.json}"

if [[ ! -d "${SOURCE_DIR}" ]]; then
  echo "ERROR: no existe directorio fuente ${SOURCE_DIR}" >&2
  exit 1
fi

if [[ ! -f "${SOURCE_DIR}/Dockerfile" ]]; then
  echo "ERROR: falta Dockerfile en ${SOURCE_DIR}" >&2
  exit 1
fi

CONFIG_FILE="${SOURCE_DIR}/config/config.json"
GCS_BUCKET="${_BUCKET_NAME:-}"
GCS_REGION=""
if [[ -f "${CONFIG_FILE}" ]]; then
  if [[ -z "${GCS_BUCKET}" ]]; then
    GCS_BUCKET="$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['gcp']['bucket_name'])")"
  fi
  GCS_REGION="$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}'))['gcp']['region'])")"
fi

LOCATION="${_LOCATION:-${GCS_REGION:-us-central1}}"
SCHEDULER_NAME="${_SCHEDULER_NAME:-${_JOB_NAME}-daily}"

ENV_VARS="CONFIG_PATH=${CONFIG_PATH},PYTHONUNBUFFERED=1"
ENV_VARS+=",GCP_PROJECT_ID=${_PROJECT_ID}"
ENV_VARS+=",GCP_BUCKET_NAME=${_BUCKET_NAME}"
ENV_VARS+=",GCP_DATASET_ID=${_DATASET_ID}"
ENV_VARS+=",GCP_REGION=${LOCATION}"
ENV_VARS+=",GCP_JOB_NAME=${_JOB_NAME}"
ENV_VARS+=",GCP_SERVICE_ACCOUNT_EMAIL=${_SERVICE_ACCOUNT}"
ENV_VARS+=",GCP_SCHEDULER_NAME=${SCHEDULER_NAME}"
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

ensure_gcs_bucket() {
  local bucket="$1"
  if [[ -z "${bucket}" ]]; then
    echo "WARN: sin gcp.bucket_name en ${CONFIG_FILE}; omitiendo creación de bucket"
    return 0
  fi

  echo "=== Bucket destino GCS: gs://${bucket} ==="
  gcloud services enable storage.googleapis.com --project="${_PROJECT_ID}" --quiet

  if gcloud storage buckets describe "gs://${bucket}" --project="${_PROJECT_ID}" &>/dev/null; then
    echo "OK bucket ya existe: gs://${bucket}"
  else
    echo "Creando bucket gs://${bucket} en ${LOCATION}..."
    gcloud storage buckets create "gs://${bucket}" \
      --project="${_PROJECT_ID}" \
      --location="${LOCATION}" \
      --uniform-bucket-level-access
    echo "OK bucket creado"
  fi

  echo "IAM objectAdmin para SA del job en gs://${bucket}"
  gcloud storage buckets add-iam-policy-binding "gs://${bucket}" \
    --member="serviceAccount:${_SERVICE_ACCOUNT}" \
    --role="roles/storage.objectAdmin" \
    --quiet
}

echo "=== Habilitando APIs ==="
gcloud services enable run.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com \
  --project="${_PROJECT_ID}" --quiet

ensure_gcs_bucket "${GCS_BUCKET}"

DEPLOY_ARGS=(
  run jobs deploy "${_JOB_NAME}"
  --project="${_PROJECT_ID}"
  --region="${LOCATION}"
  --source="${SOURCE_DIR}"
  --service-account="${_SERVICE_ACCOUNT}"
  --set-env-vars="${ENV_VARS}"
  --memory="${MEMORY}"
  --cpu="${CPU}"
  --max-retries="${MAX_RETRIES}"
  --task-timeout="${TASK_TIMEOUT}"
)

echo "=== gcloud run jobs deploy ${_JOB_NAME} (source: ${SOURCE_DIR}/ + Dockerfile) ==="
gcloud "${DEPLOY_ARGS[@]}"

echo "=== Deploy OK ==="
echo "Ejecutar manualmente:"
echo "  gcloud run jobs execute ${_JOB_NAME} --region=${LOCATION} --project=${_PROJECT_ID}"
