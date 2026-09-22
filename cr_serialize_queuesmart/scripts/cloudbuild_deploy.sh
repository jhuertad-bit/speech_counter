#!/usr/bin/env bash
# Deploy Cloud Run Job cr_serialize_queuesmart (Whisper → hist VASO).
# GPU: _USE_GPU=true → --gpu=1 --gpu-type=nvidia-l4 --no-gpu-zonal-redundancy
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
_IMAGE_NAME="$(trim "${_IMAGE_NAME:-queuesmart-audio-serialize-whisper-gpu}")"
_IMAGE_TAG="$(trim "${_IMAGE_TAG:-latest}")"
_MEMORY="$(trim "${_MEMORY:-16Gi}")"
_CPU="$(trim "${_CPU:-8}")"
# Con GPU el máximo permitido es 3600s; sin GPU se puede subir a 86400s
_TASK_TIMEOUT="$(trim "${_TASK_TIMEOUT:-3600s}")"
_MAX_RETRIES="$(trim "${_MAX_RETRIES:-1}")"
_PARALLELISM="$(trim "${_PARALLELISM:-3}")"
_WHISPER_MODEL="$(trim "${_WHISPER_MODEL:-turbo}")"
_DATASET_RAW_QUEUE="$(trim "${_DATASET_RAW_QUEUE:-raw_queue_smart}")"
_DATASET_HIST="$(trim "${_DATASET_HIST:-adf_speech_analytics}")"
_TABLE_HIST_RAW="$(trim "${_TABLE_HIST_RAW:-hist_queuesmart_mp3_whisper_vaso_raw}")"
_TABLE_HIST_PRD="$(trim "${_TABLE_HIST_PRD:-hist_queuesmart_mp3_whisper_vaso_prd}")"
_TABLE_ENRICHED="$(trim "${_TABLE_ENRICHED:-queuesmart_mp3_enriched_vaso}")"
_TABLE_CATALOG="$(trim "${_TABLE_CATALOG:-hist_queesmart_mp3_catalog_vaso}")"
_USE_GPU="$(trim "${_USE_GPU:-true}")"
_GPU_TYPE="$(trim "${_GPU_TYPE:-nvidia-l4}")"

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
USE_GPU=false
case "${_USE_GPU,,}" in
  1|true|yes|on) USE_GPU=true ;;
esac

whisper_device="cpu"
whisper_compute="int8"
accelerator="cpu"
if [[ "${USE_GPU}" == "true" ]]; then
  whisper_device="cuda"
  whisper_compute="float16"
  accelerator="gpu"
fi

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
ENV_VARS+=",WHISPER_DEVICE=${whisper_device}"
ENV_VARS+=",WHISPER_COMPUTE_TYPE=${whisper_compute}"
ENV_VARS+=",WHISPER_BEAM_SIZE=1"
ENV_VARS+=",WHISPER_WORD_TIMESTAMPS=false"
ENV_VARS+=",WHISPER_CONDITION_ON_PREVIOUS=false"
ENV_VARS+=",WHISPER_DOWNLOAD_ROOT=/app/models"
ENV_VARS+=",HF_HUB_OFFLINE=1"
ENV_VARS+=",TRANSFORMERS_OFFLINE=1"

echo "=== Habilitando APIs ==="
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  containerregistry.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  --project="${_PROJECT_ID}" --quiet

echo "=== Deploy Cloud Run Job ${_JOB_NAME} (device=${whisper_device}) ==="
echo "Imagen: ${IMAGE}"

task_timeout="${_TASK_TIMEOUT}"
if [[ "${USE_GPU}" == "true" ]]; then
  case "${task_timeout}" in
    *s) _to="${task_timeout%s}" ;;
    *) _to="${task_timeout}" ;;
  esac
  if [[ "${_to}" =~ ^[0-9]+$ ]] && (( _to > 3600 )); then
    echo "WARN: GPU limita task-timeout a 3600s (venía ${task_timeout}) → 3600s" >&2
    task_timeout="3600s"
  fi
fi

echo "Memory/CPU: ${_MEMORY} / ${_CPU} | timeout=${task_timeout} | gpu=${USE_GPU}"

deploy_args=(
  --project="${_PROJECT_ID}"
  --region="${_LOCATION}"
  --image="${IMAGE}"
  --service-account="${_SERVICE_ACCOUNT}"
  --set-env-vars="${ENV_VARS}"
  --labels="project=queuesmart,component=serializer-whisper,env=prd,team=data-engineering,cost-center=utpbi,accelerator=${accelerator}"
  --memory="${_MEMORY}"
  --cpu="${_CPU}"
  --max-retries="${_MAX_RETRIES}"
  --task-timeout="${task_timeout}"
  --parallelism="${_PARALLELISM}"
  --tasks=1
)

if [[ "${USE_GPU}" == "true" ]]; then
  deploy_args+=(
    --gpu=1
    --gpu-type="${_GPU_TYPE}"
    --no-gpu-zonal-redundancy
  )
fi

gcloud run jobs deploy "${_JOB_NAME}" "${deploy_args[@]}"

echo "=== Deploy OK (VASO — Whisper [MM:SS], device=${whisper_device}) ==="
echo "Destino:"
echo "  ${_PROJECT_ID}.${_DATASET_HIST}.${_TABLE_HIST_RAW}"
echo "  ${_PROJECT_ID}.${_DATASET_HIST}.${_TABLE_HIST_PRD}"
echo "Ejecutar un día:"
echo "  gcloud run jobs execute ${_JOB_NAME} \\"
echo "    --region=${_LOCATION} --project=${_PROJECT_ID} \\"
echo "    --update-env-vars=FECHA_AUDIO=YYYY-MM-DD"
