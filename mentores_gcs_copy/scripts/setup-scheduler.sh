#!/bin/bash
# Scheduler diario 03:00 America/Lima → Cloud Workflow mentores GCS copy (ayer).
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-prd-utpbi-data-operation}"
REGION="${GCP_REGION:-us-central1}"
SCHEDULER_NAME="${GCP_SCHEDULER_NAME:-prd-sch-mentores-gcs-copy}"
WORKFLOW_NAME="${GCP_WORKFLOW_NAME:-prd-utpbi-mentores-gcs-copy}"
SERVICE_ACCOUNT="${GCP_SERVICE_ACCOUNT_EMAIL:-genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com}"
SCHEDULE="${GCP_SCHEDULE:-0 3 * * *}"
TIME_ZONE="${GCP_TIME_ZONE:-America/Lima}"

URI="https://workflowexecutions.googleapis.com/v1/projects/${PROJECT_ID}/locations/${REGION}/workflows/${WORKFLOW_NAME}/executions"

echo "Project:   $PROJECT_ID"
echo "Scheduler: $SCHEDULER_NAME"
echo "Workflow:  $WORKFLOW_NAME"
echo "Cron:      $SCHEDULE ($TIME_ZONE)"

gcloud services enable cloudscheduler.googleapis.com workflows.googleapis.com \
  --project="$PROJECT_ID"

if gcloud scheduler jobs describe "$SCHEDULER_NAME" \
  --project="$PROJECT_ID" --location="$REGION" &>/dev/null; then
  echo "Actualizando scheduler existente..."
  gcloud scheduler jobs update http "$SCHEDULER_NAME" \
    --project="$PROJECT_ID" \
    --location="$REGION" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIME_ZONE" \
    --uri="$URI" \
    --http-method=POST \
    --oauth-service-account-email="$SERVICE_ACCOUNT" \
    --message-body='{}'
else
  echo "Creando scheduler..."
  gcloud scheduler jobs create http "$SCHEDULER_NAME" \
    --project="$PROJECT_ID" \
    --location="$REGION" \
    --schedule="$SCHEDULE" \
    --time-zone="$TIME_ZONE" \
    --uri="$URI" \
    --http-method=POST \
    --oauth-service-account-email="$SERVICE_ACCOUNT" \
    --message-body='{}'
fi

echo "OK. Prueba:"
echo "  gcloud scheduler jobs run $SCHEDULER_NAME --project=$PROJECT_ID --location=$REGION"
