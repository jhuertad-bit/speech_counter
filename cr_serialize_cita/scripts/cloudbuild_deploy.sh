#!/usr/bin/env bash
# Deploy 1 o 2 Cloud Run Jobs (promotor / mentor) sobre la misma imagen.
set -euo pipefail

trim() {
  local v="${1:-}"
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  printf '%s' "$v"
}

_PROJECT_ID="$(trim "${_PROJECT_ID:-}")"
_SERVICE_ACCOUNT="$(trim "${_SERVICE_ACCOUNT:-}")"
_LOCATION="$(trim "${_LOCATION:-us-central1}")"
_IMAGE_NAME="$(trim "${_IMAGE_NAME:-cita-audio-serialize-whisper}")"
_IMAGE_TAG="$(trim "${_IMAGE_TAG:-latest}")"
_MEMORY="$(trim "${_MEMORY:-32Gi}")"
_CPU="$(trim "${_CPU:-8}")"
_TASK_TIMEOUT="$(trim "${_TASK_TIMEOUT:-86400s}")"
_MAX_RETRIES="$(trim "${_MAX_RETRIES:-1}")"
_PARALLELISM="$(trim "${_PARALLELISM:-10}")"
_WHISPER_MODEL="$(trim "${_WHISPER_MODEL:-turbo}")"
_DATASET="$(trim "${_DATASET:-raw_cita_promotor}")"
_DEPLOY_CANALES="$(trim "${_DEPLOY_CANALES:-promotor,mentor}")"

missing=0
for name in _PROJECT_ID _SERVICE_ACCOUNT; do
  if [[ -z "${!name}" ]]; then
    echo "ERROR: falta ${name}" >&2
    missing=1
  fi
done
[[ "${missing}" -eq 0 ]] || exit 1

IMAGE="gcr.io/${_PROJECT_ID}/${_IMAGE_NAME}:${_IMAGE_TAG}"

gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com containerregistry.googleapis.com \
  bigquery.googleapis.com storage.googleapis.com \
  --project="${_PROJECT_ID}" --quiet

deploy_one() {
  local canal="$1"
  local job_name bucket catalog raw prd
  if [[ "${canal}" == "promotor" ]]; then
    job_name="prd-utpbi-cita-promotor-audio-serialize-whisper"
    bucket="prd-utp-stg-citapromotor-9bd1430535b8"
    catalog="hist_cita_promotor_audio_catalog"
    raw="hist_cita_promotor_audio_whisper_raw"
    prd="hist_cita_promotor_audio_whisper_prd"
  elif [[ "${canal}" == "mentor" ]]; then
    job_name="prd-utpbi-cita-mentor-audio-serialize-whisper"
    bucket="prd-utp-stg-mentores"
    catalog="hist_cita_mentor_audio_catalog"
    raw="hist_cita_mentor_audio_whisper_raw"
    prd="hist_cita_mentor_audio_whisper_prd"
  else
    echo "ERROR: canal desconocido ${canal}" >&2
    return 1
  fi

  local env="PYTHONUNBUFFERED=1,WHISPER_MODEL=${_WHISPER_MODEL},CITA_CANAL=${canal}"
  env+=",GCP_PROJECT_ID=${_PROJECT_ID},GCP_BUCKET_AUDIO=${bucket}"
  env+=",GCP_REGION=${_LOCATION},GCP_JOB_NAME=${job_name}"
  env+=",GCP_SERVICE_ACCOUNT_EMAIL=${_SERVICE_ACCOUNT}"
  env+=",CITA_DATASET=${_DATASET}"
  env+=",CITA_TABLE_CATALOG=${catalog}"
  env+=",CITA_TABLE_WHISPER_RAW=${raw}"
  env+=",CITA_TABLE_WHISPER_PRD=${prd}"
  env+=",WHISPER_BEAM_SIZE=3,WHISPER_WORD_TIMESTAMPS=false,WHISPER_CONDITION_ON_PREVIOUS=false"
  env+=",HF_HUB_OFFLINE=1,TRANSFORMERS_OFFLINE=1"

  echo "=== Deploy Job ${job_name} (canal=${canal}) ==="
  gcloud run jobs deploy "${job_name}" \
    --project="${_PROJECT_ID}" \
    --region="${_LOCATION}" \
    --image="${IMAGE}" \
    --service-account="${_SERVICE_ACCOUNT}" \
    --set-env-vars="${env}" \
    --memory="${_MEMORY}" \
    --cpu="${_CPU}" \
    --max-retries="${_MAX_RETRIES}" \
    --task-timeout="${_TASK_TIMEOUT}" \
    --parallelism="${_PARALLELISM}" \
    --tasks=1
  echo "OK ${job_name} → ${_DATASET}.${raw} / ${prd}"
}

IFS=',' read -r -a canales <<< "${_DEPLOY_CANALES}"
for c in "${canales[@]}"; do
  c="$(trim "${c}")"
  [[ -n "${c}" ]] || continue
  deploy_one "${c}"
done
