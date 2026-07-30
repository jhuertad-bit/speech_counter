#!/usr/bin/env bash
# Deploy Cloud Run Job qsmart_transcribe (STT Chirp 3 + diarización).
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

trim() { local v="${1:-}"; v="${v#"${v%%[![:space:]]*}"}"; v="${v%"${v##*[![:space:]]}"}"; printf '%s' "$v"; }

_PROJECT_ID="$(trim "${_PROJECT_ID:-}")"
_JOB_NAME="$(trim "${_JOB_NAME:-}")"
_SERVICE_ACCOUNT="$(trim "${_SERVICE_ACCOUNT:-}")"
_BUCKET_NAME="$(trim "${_BUCKET_NAME:-}")"
_LOCATION="$(trim "${_LOCATION:-}")"
_SOURCE_DIR="$(trim "${_SOURCE_DIR:-}")"
_MEMORY="$(trim "${_MEMORY:-}")"
_CPU="$(trim "${_CPU:-}")"
_TASK_TIMEOUT="$(trim "${_TASK_TIMEOUT:-}")"
_MAX_RETRIES="$(trim "${_MAX_RETRIES:-}")"
_PARALLELISM="$(trim "${_PARALLELISM:-}")"
_CONFIG_PATH="$(trim "${_CONFIG_PATH:-}")"
_STT_LOCATION="$(trim "${_STT_LOCATION:-}")"
_STT_MODEL="$(trim "${_STT_MODEL:-}")"
_MANIFEST_PREFIX="$(trim "${_MANIFEST_PREFIX:-}")"
_BQ_LOCATION="$(trim "${_BQ_LOCATION:-}")"
_ENRICHED_TABLE="$(trim "${_ENRICHED_TABLE:-}")"
_HIST_RAW_TABLE="$(trim "${_HIST_RAW_TABLE:-}")"
_HIST_PRD_TABLE="$(trim "${_HIST_PRD_TABLE:-}")"

echo "=== Validando variables del activador ==="
require "_PROJECT_ID" "${_PROJECT_ID}"
require "_JOB_NAME" "${_JOB_NAME}"
require "_SERVICE_ACCOUNT" "${_SERVICE_ACCOUNT}"
require "_BUCKET_NAME" "${_BUCKET_NAME}"
if [[ -n "${_SERVICE_ACCOUNT}" && "${_SERVICE_ACCOUNT}" != *"@"* ]]; then
  echo "ERROR: _SERVICE_ACCOUNT debe ser email completo (ej. nombre@${_PROJECT_ID}.iam.gserviceaccount.com), no '${_SERVICE_ACCOUNT}'" >&2
  missing=1
fi

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

SOURCE_DIR="${_SOURCE_DIR:-qsmart_transcribe/src}"
TASK_TIMEOUT="${_TASK_TIMEOUT:-3600s}"
MAX_RETRIES="${_MAX_RETRIES:-1}"
PARALLELISM="${_PARALLELISM:-10}"
CONFIG_PATH="${_CONFIG_PATH:-/app/config/config.json}"
MEMORY="${_MEMORY:-1Gi}"
CPU="${_CPU:-1}"
LOCATION="${_LOCATION:-us-central1}"
STT_LOCATION="${_STT_LOCATION:-us}"
STT_MODEL="${_STT_MODEL:-chirp_3}"
MANIFEST_PREFIX="${_MANIFEST_PREFIX:-state/stt_manifests}"
BQ_LOCATION="${_BQ_LOCATION:-US}"

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
ENV_VARS+=",GCP_REGION=${LOCATION}"
ENV_VARS+=",GCP_JOB_NAME=${_JOB_NAME}"
ENV_VARS+=",GCP_SERVICE_ACCOUNT_EMAIL=${_SERVICE_ACCOUNT}"
ENV_VARS+=",GCP_STT_LOCATION=${STT_LOCATION}"
ENV_VARS+=",GCP_BQ_LOCATION=${BQ_LOCATION}"
ENV_VARS+=",QS_STT_MODEL=${STT_MODEL}"
ENV_VARS+=",QS_MANIFEST_PREFIX=${MANIFEST_PREFIX}"
if [[ -n "${_ENRICHED_TABLE}" ]]; then
  ENV_VARS+=",QS_ENRICHED_TABLE=${_ENRICHED_TABLE}"
fi
if [[ -n "${_HIST_RAW_TABLE}" ]]; then
  ENV_VARS+=",QS_HIST_RAW_TABLE=${_HIST_RAW_TABLE}"
fi
if [[ -n "${_HIST_PRD_TABLE}" ]]; then
  ENV_VARS+=",QS_HIST_PRD_TABLE=${_HIST_PRD_TABLE}"
fi

ensure_gcs_bucket() {
  local bucket="$1"
  echo "=== Bucket GCS: gs://${bucket} ==="
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
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  speech.googleapis.com \
  bigquery.googleapis.com \
  --project="${_PROJECT_ID}" --quiet

ensure_gcs_bucket "${_BUCKET_NAME}"

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
  --parallelism="${PARALLELISM}"
  --tasks=1
)

echo "=== gcloud run jobs deploy ${_JOB_NAME} (source: ${SOURCE_DIR}/ + Dockerfile) ==="
gcloud "${DEPLOY_ARGS[@]}"

echo "=== Deploy OK ==="
echo "Orquestación: Cloud Workflows (queuesmart/workflows/daily_pipeline.yaml)"
echo "Manual prepare:"
echo "  gcloud run jobs execute ${_JOB_NAME} --region=${LOCATION} --project=${_PROJECT_ID} \\"
echo "    --tasks=1 --update-env-vars=QS_JOB_ROLE=prepare,SYNC_PROCESS_DATE=YYYY-MM-DD"
echo "Manual worker (N = count del manifiesto):"
echo "  gcloud run jobs execute ${_JOB_NAME} --region=${LOCATION} --project=${_PROJECT_ID} \\"
echo "    --tasks=N --update-env-vars=QS_JOB_ROLE=worker,SYNC_PROCESS_DATE=YYYY-MM-DD"
