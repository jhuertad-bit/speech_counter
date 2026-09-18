#!/usr/bin/env bash
# ============================================================
# deploy.sh — Cloud Run Job: cr_serialize_queuesmart
#
# Whisper LOCAL → tablas VASO (sin diarización).
#
# Uso:
#   chmod +x deploy.sh
#   ./deploy.sh
# ============================================================

set -euo pipefail

CONFIG_FILE="$(dirname "$0")/src/config/config.json"

PROJECT_ID=$(jq -r '.gcp.project_id'           "$CONFIG_FILE")
REGION=$(jq -r '.gcp.region'                   "$CONFIG_FILE")
JOB_NAME=$(jq -r '.gcp.cloud_run_job_name'     "$CONFIG_FILE")
IMAGE=$(jq -r '.gcp.docker_image_repository'   "$CONFIG_FILE")
SA_EMAIL=$(jq -r '.gcp.service_account_email'  "$CONFIG_FILE")

WHISPER_MODEL="${WHISPER_MODEL:-turbo}"

echo "============================================================"
echo "  Deploy: Cloud Run Job — cr_serialize_queuesmart"
echo "============================================================"
echo "  Proyecto  : $PROJECT_ID"
echo "  Región    : $REGION"
echo "  Job       : $JOB_NAME"
echo "  Imagen    : $IMAGE"
echo "  SA Email  : $SA_EMAIL"
echo "  Whisper   : $WHISPER_MODEL (LOCAL, sin hablantes)"
echo "============================================================"

echo ""
echo "[1/4] Activando APIs..."
gcloud services enable \
    run.googleapis.com \
    containerregistry.googleapis.com \
    bigquery.googleapis.com \
    storage.googleapis.com \
    --project="$PROJECT_ID"

echo ""
echo "[2/4] Build + push imagen (contexto src/, incluye modelo Whisper)..."
gcloud builds submit "$(dirname "$0")/src" \
    --project="$PROJECT_ID" \
    --tag="$IMAGE" \
    --timeout="1800s"
echo "      ✓ $IMAGE"

echo ""
echo "[3/4] Crear / actualizar Cloud Run Job..."
JOB_EXISTS=$(gcloud run jobs describe "$JOB_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(name)" 2>/dev/null || echo "")

COMMON_FLAGS=(
    --image="$IMAGE"
    --region="$REGION"
    --project="$PROJECT_ID"
    --service-account="$SA_EMAIL"
    --memory="32Gi"
    --cpu="8"
    --task-timeout="86400s"
    --max-retries="1"
    --set-env-vars="WHISPER_MODEL=$WHISPER_MODEL,WHISPER_BEAM_SIZE=1,WHISPER_WORD_TIMESTAMPS=false,WHISPER_CONDITION_ON_PREVIOUS=false,WHISPER_DOWNLOAD_ROOT=/app/models,HF_HUB_OFFLINE=1,TRANSFORMERS_OFFLINE=1"
    --labels="project=queuesmart,component=serializer-whisper,env=prd,team=data-engineering,cost-center=utpbi"
    --parallelism=10
    --tasks=1
)

if [[ -z "$JOB_EXISTS" ]]; then
    gcloud run jobs create "$JOB_NAME" "${COMMON_FLAGS[@]}"
else
    gcloud run jobs update "$JOB_NAME" "${COMMON_FLAGS[@]}"
fi
echo "      ✓ Job $JOB_NAME listo"

echo ""
echo "[4/4] Verificar..."
gcloud run jobs describe "$JOB_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="table(
        name,
        spec.template.spec.containers[0].image,
        spec.template.spec.serviceAccountName,
        spec.template.spec.containers[0].resources.limits.memory,
        spec.template.spec.containers[0].resources.limits.cpu
    )"

echo ""
echo "============================================================"
echo "  ✓ Deploy OK — $JOB_NAME ($REGION)"
echo ""
echo "  MODO DÍA:"
echo "    gcloud run jobs execute $JOB_NAME \\"
echo "      --region=$REGION --project=$PROJECT_ID \\"
echo "      --update-env-vars=FECHA_AUDIO=2026-09-10"
echo ""
echo "  Destino VASO:"
echo "    adf_speech_analytics.hist_queuesmart_mp3_whisper_vaso_raw"
echo "    adf_speech_analytics.hist_queuesmart_mp3_whisper_vaso_prd"
echo "============================================================"
