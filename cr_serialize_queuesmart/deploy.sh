#!/usr/bin/env bash
# ============================================================
# deploy.sh — Cloud Run Job: cr_serialize_queuesmart
#
# Paso PARALELO al STT Chirp. No modifica queuesmart STT productivo.
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
echo "  Whisper   : $WHISPER_MODEL (LOCAL)"
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
    --memory="16Gi"
    --cpu="4"
    --task-timeout="14400s"
    --max-retries="1"
    --set-env-vars="WHISPER_MODEL=$WHISPER_MODEL"
    --labels="project=queuesmart,component=serializer-whisper,env=prd,team=data-engineering,cost-center=utpbi"
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
echo "  MODO DÍA (producción / backfill):"
echo "    gcloud run jobs execute $JOB_NAME \\"
echo "      --region=$REGION --project=$PROJECT_ID \\"
echo "      --update-env-vars=FECHA_AUDIO=2026-09-10"
echo ""
echo "  MODO LISTA (pruebas):"
echo "    gcloud run jobs execute $JOB_NAME \\"
echo "      --region=$REGION --project=$PROJECT_ID \\"
echo "      --update-env-vars=GCS_URIS='gs://prd-utp-stg-queuesmart/data/input/queuesmart_mp3/imported_from_s3/2026-09-10/035RA1-20260910-105220.flac'"
echo ""
echo "  Destino = mismas tablas STT (Chirp):"
echo "    adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_raw"
echo "    adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_prd"
echo "  Downstream Gemini: sp_queuesmart_audio_analisis_ia (sin cambios)"
echo "============================================================"
