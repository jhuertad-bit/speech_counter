#!/usr/bin/env bash
# Deploy Cloud Run Job cr_serialize_queuesmart (Whisper → hist STT).
# Invocado por Cloud Build tras build+push de la imagen.
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

trim() {
  local v="${1:-}"
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  printf '%s' "$v"
}

_PROJECT_ID="$(trim "${_PROJECT_ID:-}")"
_JOB_NAME="$(trim "${_JOB_NAME:-}")"
_SERVICE_ACCOUNT="$(trim "${_SERVICE_ACCOUNT:-}")"
_BUCKET_NAME="$(trim "${_BUCKET_NAME:-}")"
_LOCATION="$(trim "${_LOCATION:-us-central1}")"
_IMAGE_NAME="$(trim "${_IMAGE_NAME:-queuesmart-audio-serialize-whisper-vaso}")"
_IMAGE_TAG="$(trim "${_IMAGE_TAG:-latest}")"
_MEMORY="$(trim "${_MEMORY:-16Gi}")"
_CPU="$(trim "${_CPU:-4}")"
_TASK_TIMEOUT="$(trim "${_TASK_TIMEOUT:-14400s}")"
_MAX_RETRIES="$(trim "${_MAX_RETRIES:-1}")"
_PARALLELISM="$(trim "${_PARALLELISM:-1}")"
_WHISPER_MODEL="$(trim "${_WHISPER_MODEL:-turbo}")"
_DATASET_RAW_QUEUE="$(trim "${_DATASET_RAW_QUEUE:-raw_queue_smart}")"
_DATASET_HIST="$(trim "${_DATASET_HIST:-adf_speech_analytics}")"
_TABLE_HIST_RAW="$(trim "${_TABLE_HIST_RAW:-hist_queuesmart_mp3_whisper_vaso_raw}")"
_TABLE_HIST_PRD="$(trim "${_TABLE_HIST_PRD:-hist_queuesmart_mp3_whisper_vaso_prd}")"
_TABLE_ENRICHED="$(trim "${_TABLE_ENRICHED:-queuesmart_mp3_enriched}")"
_TABLE_CATALOG="$(trim "${_TABLE_CATALOG:-hist_queesmart_mp3_catalog}")"

echo "=== Validando variables del activador ==="
require "_PROJECT_ID" "${_PROJECT_ID}"
require "_JOB_NAME" "${_JOB_NAME}"
require "_SERVICE_ACCOUNT" "${_SERVICE_ACCOUNT}"
require "_BUCKET_NAME" "${_BUCKET_NAME}"

if [[ -n "${_SERVICE_ACCOUNT}" && "${_SERVICE_ACCOUNT}" != *"@"* ]]; then
  echo "ERROR: _SERVICE_ACCOUNT debe ser email completo (ej. nombre@${_PROJECT_ID}.iam.gserviceaccount.com)" >&2
  missing=1
fi

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

IMAGE="gcr.io/${_PROJECT_ID}/${_IMAGE_NAME}:${_IMAGE_TAG}"

ENV_VARS="PYTHONUNBUFFERED=1"
ENV_VARS+=",WHISPER_MODEL=${_WHISPER_MODEL}"
ENV_VARS+=",GCP_PROJECT_ID=${_PROJECT_ID}"
ENV_VARS+=",GCP_BUCKET_AUDIO=${_BUCKET_NAME}"
ENV_VARS+=",GCP_REGION=${_LOCATION}"
ENV_VARS+=",GCP_JOB_NAME=${_JOB_NAME}"
ENV_VARS+=",GCP_SERVICE_ACCOUNT_EMAIL=${_SERVICE_ACCOUNT}"
ENV_VARS+=",QS_DATASET_RAW_QUEUE=${_DATASET_RAW_QUEUE}"
ENV_VARS+=",QS_DATASET_HIST=${_DATASET_HIST}"
ENV_VARS+=",QS_TABLE_HIST_RAW=${_TABLE_HIST_RAW}"
ENV_VARS+=",QS_TABLE_HIST_PRD=${_TABLE_HIST_PRD}"
ENV_VARS+=",QS_TABLE_ENRICHED=${_TABLE_ENRICHED}"
ENV_VARS+=",QS_TABLE_CATALOG=${_TABLE_CATALOG}"

echo "=== Habilitando APIs ==="
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  containerregistry.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  --project="${_PROJECT_ID}" --quiet

echo "=== Deploy Cloud Run Job ${_JOB_NAME} ==="
echo "Imagen: ${IMAGE}"
echo "Memory/CPU: ${_MEMORY} / ${_CPU} | timeout=${_TASK_TIMEOUT}"

gcloud run jobs deploy "${_JOB_NAME}" \
  --project="${_PROJECT_ID}" \
  --region="${_LOCATION}" \
  --image="${IMAGE}" \
  --service-account="${_SERVICE_ACCOUNT}" \
  --set-env-vars="${ENV_VARS}" \
  --memory="${_MEMORY}" \
  --cpu="${_CPU}" \
  --max-retries="${_MAX_RETRIES}" \
  --task-timeout="${_TASK_TIMEOUT}" \
  --parallelism="${_PARALLELISM}" \
  --tasks=1

echo "=== Deploy OK (VASO — no escribe hist Chirp) ==="
echo "Destino:"
echo "  ${_PROJECT_ID}.${_DATASET_HIST}.${_TABLE_HIST_RAW}"
echo "  ${_PROJECT_ID}.${_DATASET_HIST}.${_TABLE_HIST_PRD}"
echo "Ejecutar un día:"
echo "  gcloud run jobs execute ${_JOB_NAME} \\"
echo "    --region=${_LOCATION} --project=${_PROJECT_ID} \\"
echo "    --update-env-vars=FECHA_AUDIO=YYYY-MM-DD"
echo ""
echo "Prueba URI:"
echo "  gcloud run jobs execute ${_JOB_NAME} \\"
echo "    --region=${_LOCATION} --project=${_PROJECT_ID} \\"
echo "    --update-env-vars=GCS_URIS='gs://${_BUCKET_NAME}/data/input/queuesmart_mp3/imported_from_s3/YYYY-MM-DD/ARCHIVO.flac'"
