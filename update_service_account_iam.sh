#!/usr/bin/env bash
# =============================================================================
# update_service_account_iam.sh
#
# Asigna roles IAM a las cuentas de servicio de este monorepo según el análisis
# de los .py y los pipelines cloudbuild.yaml.
#
# Hay DOS cuentas distintas:
#
#   1) RUNTIME  — la SA que ejecutan Cloud Functions / Cloud Run en producción
#                 (_SERVICE_ACCOUNT en Cloud Build). Usada por el código Python.
#
#   2) CLOUDBUILD — la SA que ejecuta los pipelines de Cloud Build
#                   (p.ej. PROJECT_NUMBER@cloudbuild.gserviceaccount.com).
#
# Uso:
#   ./update_service_account_iam.sh discover <PROJECT_ID>
#   ./update_service_account_iam.sh runtime  <PROJECT_ID> <SA_EMAIL> [BUCKET] [DATASET] [OAUTH_SECRET]
#   ./update_service_account_iam.sh cloudbuild <PROJECT_ID> [SA_EMAIL|default] [--runtime-sa=...] [--public-invoker]
#
# Ejemplos:
#   ./update_service_account_iam.sh discover dev-utpbi-data-operation
#
#   ./update_service_account_iam.sh runtime \
#     dev-utpbi-data-operation \
#     dev-utp-eduflow-sa@dev-utpbi-data-operation.iam.gserviceaccount.com \
#     dev-utp-stg-onemarketer-k7m4n9p2q8r5t3v6w1x0 \
#     raw_onemarketer
#
#   ./update_service_account_iam.sh cloudbuild dev-utpbi-data-operation \
#     dev-utp-eduflow-sa@dev-utpbi-data-operation.iam.gserviceaccount.com \
#     --runtime-sa=dev-utp-eduflow-sa@dev-utpbi-data-operation.iam.gserviceaccount.com
#
# Requiere: gcloud autenticado con permisos para administrar IAM en el proyecto.
# =============================================================================
set -euo pipefail

# Defaults del proyecto dev (override con env vars si aplica)
DEFAULT_PROJECT="${DEFAULT_PROJECT:-dev-utpbi-data-operation}"
DEFAULT_RUNTIME_SA="${DEFAULT_RUNTIME_SA:-dev-utp-eduflow-sa@${DEFAULT_PROJECT}.iam.gserviceaccount.com}"
DEFAULT_BUCKET="${DEFAULT_BUCKET:-dev-utp-stg-onemarketer-k7m4n9p2q8r5t3v6w1x0}"
DEFAULT_DATASET="${DEFAULT_DATASET:-raw_onemarketer}"
DEFAULT_OAUTH_SECRET="${DEFAULT_OAUTH_SECRET:-dev_secret_onemarketer_api}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

usage() {
  sed -n '2,35p' "$0" | sed 's/^# \?//'
  exit 1
}

ensure_gcloud_project() {
  local project="$1"
  gcloud config set project "${project}" --quiet
}

resolve_cloudbuild_sa() {
  local project="$1"
  local sa_input="${2:-default}"

  if [[ -z "${sa_input}" || "${sa_input}" == "default" || "${sa_input}" == "auto" ]]; then
    local resolved
    resolved="$(gcloud builds get-default-service-account --project="${project}" 2>/dev/null || true)"
    if [[ -n "${resolved}" ]]; then
      echo "${resolved}"
      return 0
    fi

    local project_number
    project_number="$(gcloud projects describe "${project}" --format='value(projectNumber)')"
    echo "${project_number}@cloudbuild.gserviceaccount.com"
    return 0
  fi

  echo "${sa_input}"
}

validate_sa_exists() {
  local project="$1"
  local sa_email="$2"

  if gcloud iam service-accounts describe "${sa_email}" --project="${project}" &>/dev/null; then
    return 0
  fi

  error "La cuenta de servicio no existe: ${sa_email}"
  echo ""
  echo "Obtén el email correcto con:"
  echo "  ./update_service_account_iam.sh discover ${project}"
  echo ""
  echo "Para Cloud Build usa 'default' (no el número de ejemplo del README):"
  echo "  ./update_service_account_iam.sh cloudbuild ${project} default"
  exit 1
}

discover_accounts() {
  local project="$1"
  ensure_gcloud_project "${project}"

  local project_number cloudbuild_sa runtime_sa
  project_number="$(gcloud projects describe "${project}" --format='value(projectNumber)')"
  cloudbuild_sa="$(resolve_cloudbuild_sa "${project}" "default")"
  runtime_sa="${DEFAULT_RUNTIME_SA/dev-utpbi-data-operation/${project}}"

  cat <<EOF
Proyecto: ${project}
Project number: ${project_number}

SA de este repo (runtime + posible trigger Cloud Build):
  ${runtime_sa}

Cloud Build SA default del proyecto (si el trigger no usa SA custom):
  ${cloudbuild_sa}

Comandos sugeridos con tu SA:

  # Permisos para ejecutar el código Python (GCS, BigQuery, Secrets)
  ./update_service_account_iam.sh runtime ${project} ${runtime_sa} \\
    ${DEFAULT_BUCKET} ${DEFAULT_DATASET} ${DEFAULT_OAUTH_SECRET}

  # Permisos para desplegar desde Cloud Build (usa tu SA si el trigger la tiene configurada)
  ./update_service_account_iam.sh cloudbuild ${project} ${runtime_sa} \\
    --runtime-sa=${runtime_sa} --public-invoker

  # O si el trigger usa la SA default de Cloud Build:
  ./update_service_account_iam.sh cloudbuild ${project} default \\
    --runtime-sa=${runtime_sa} --public-invoker

Si el trigger de Cloud Build usa otra SA custom, revísala en:
  Console → Cloud Build → Triggers → [tu trigger] → Service account
EOF
}

bind_project_role() {
  local project="$1"
  local member="$2"
  local role="$3"

  info "Proyecto: ${role} → ${member}"
  gcloud projects add-iam-policy-binding "${project}" \
    --member="serviceAccount:${member}" \
    --role="${role}" \
    --quiet >/dev/null
}

bind_bucket_role() {
  local bucket="$1"
  local member="$2"
  local role="$3"

  info "Bucket gs://${bucket}: ${role} → ${member}"
  gcloud storage buckets add-iam-policy-binding "gs://${bucket}" \
    --member="serviceAccount:${member}" \
    --role="${role}" \
    --quiet >/dev/null
}

bind_dataset_role() {
  local project="$1"
  local dataset="$2"
  local member="$3"
  local role="$4"

  info "Dataset ${project}:${dataset}: ${role} → ${member}"
  bq add-iam-policy-binding \
    --project_id="${project}" \
    "${dataset}" \
    --member="serviceAccount:${member}" \
    --role="${role}" \
    --quiet >/dev/null
}

bind_secret_accessor() {
  local project="$1"
  local secret_id="$2"
  local member="$3"

  if ! gcloud secrets describe "${secret_id}" --project="${project}" &>/dev/null; then
    warn "Secreto '${secret_id}' no existe en ${project}; omitiendo secretAccessor."
    return 0
  fi

  info "Secreto ${secret_id}: roles/secretmanager.secretAccessor → ${member}"
  gcloud secrets add-iam-policy-binding "${secret_id}" \
    --project="${project}" \
    --member="serviceAccount:${member}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null
}

# -----------------------------------------------------------------------------
# Permisos RUNTIME (derivados de los .py)
#
# GCS  — storage.Client: upload, download, exists, metadata
#        onemarketer/src/extract_chats.py, download_chat_media.py
#        audio_to_mp3/src/main.py, onemarketer-api/src/extract_chats.py
#
# BQ   — bigquery.Client:
#        · create_dataset / create_table / get_table / delete_table (particiones)
#        · load_table_from_uri (jobs de carga desde GCS)
#        · query (DELETE fallback en bq_documentos.py)
#        · insert_rows_json (download_chat_media.py → bq_documentos.py)
#
# Secret Manager — auth_onemarketer.py (fallback ONEMARKETER_API_SECRET)
#                  Cloud Run monta el secreto vía --set-secrets (onemarketer-api)
# -----------------------------------------------------------------------------
apply_runtime_roles() {
  local project="$1"
  local sa_email="$2"
  local bucket="${3:-}"
  local dataset="${4:-}"
  local oauth_secret="${5:-}"

  info "=== SA RUNTIME: ${sa_email} ==="

  # Jobs de carga y consultas (load_table_from_uri, query, insert_rows_json)
  bind_project_role "${project}" "${sa_email}" "roles/bigquery.jobUser"

  # Crear datasets/tablas, borrar particiones, insertar filas
  if [[ -n "${dataset}" ]]; then
    bind_dataset_role "${project}" "${dataset}" "${sa_email}" "roles/bigquery.dataEditor"
  else
    warn "Sin DATASET: aplicando roles/bigquery.dataEditor a nivel proyecto (menos restrictivo)."
    bind_project_role "${project}" "${sa_email}" "roles/bigquery.dataEditor"
  fi

  # Lectura/escritura de objetos en el bucket de datos
  if [[ -n "${bucket}" ]]; then
    bind_bucket_role "${bucket}" "${sa_email}" "roles/storage.objectAdmin"
  else
    warn "Sin BUCKET: aplicando roles/storage.objectAdmin a nivel proyecto (menos restrictivo)."
    bind_project_role "${project}" "${sa_email}" "roles/storage.objectAdmin"
  fi

  # OCR — ocr_engine.py → Cloud Vision document_text_detection
  bind_project_role "${project}" "${sa_email}" "roles/cloudvision.user"

  info "Habilitando Cloud Vision API (requerida para OCR)..."
  gcloud services enable vision.googleapis.com --project="${project}" --quiet 2>/dev/null || \
    warn "No se pudo habilitar vision.googleapis.com (permisos insuficientes). Habilítala manualmente."

  # onemarketer-api: credenciales OAuth (Cloud Run --set-secrets o lectura directa)
  if [[ -n "${oauth_secret}" ]]; then
    bind_secret_accessor "${project}" "${oauth_secret}" "${sa_email}"
  fi

  cat <<EOF

${GREEN}Runtime SA configurada.${NC}

Permisos aplicados según código Python:
  · GCS:     objectAdmin en bucket (upload/download/exists/metadata)
  · BQ:      jobUser (proyecto) + dataEditor (dataset)
  · Vision:  cloudvision.user (OCR imágenes/PDF escaneados)
  · Secrets: secretAccessor (si se indicó OAUTH_SECRET)

Adicional (fuera de este script, si usas Scheduler con OIDC):
  · roles/run.invoker de esta SA sobre la Cloud Function Gen2
    Ver: onemarketer/src/scheduler-setup.sh

EOF
}

# -----------------------------------------------------------------------------
# Permisos CLOUD BUILD (derivados de cloudbuild.yaml + scripts de deploy)
#
# onemarketer/cloudbuild.yaml       → gcloud functions deploy --gen2 (source)
# audio_to_mp3/cloudbuild.yaml      → docker push + functions deploy (imagen + Eventarc GCS)
# onemarketer-api/cloudbuild.yaml   → docker push + gcloud run deploy --set-secrets
# -----------------------------------------------------------------------------
apply_cloudbuild_roles() {
  local project="$1"
  local sa_email="$2"
  local public_invoker="${3:-false}"
  local runtime_sa="${4:-}"

  info "=== SA CLOUD BUILD: ${sa_email} ==="

  bind_project_role "${project}" "${sa_email}" "roles/cloudbuild.builds.builder"
  bind_project_role "${project}" "${sa_email}" "roles/artifactregistry.writer"
  bind_project_role "${project}" "${sa_email}" "roles/cloudfunctions.developer"
  bind_project_role "${project}" "${sa_email}" "roles/run.admin"
  bind_project_role "${project}" "${sa_email}" "roles/eventarc.admin"
  bind_project_role "${project}" "${sa_email}" "roles/storage.admin"

  # Necesario para asignar --service-account= en functions deploy
  if [[ -n "${runtime_sa}" ]]; then
    info "ActAs: ${sa_email} puede impersonar ${runtime_sa}"
    gcloud iam service-accounts add-iam-policy-binding "${runtime_sa}" \
      --project="${project}" \
      --member="serviceAccount:${sa_email}" \
      --role="roles/iam.serviceAccountUser" \
      --quiet >/dev/null
  else
    warn "Sin RUNTIME_SA: agrega manualmente roles/iam.serviceAccountUser sobre la SA runtime."
  fi

  if [[ "${public_invoker}" == "true" ]]; then
    info "Modo --allow-unauthenticated / --public-invoker"
    bind_project_role "${project}" "${sa_email}" "roles/run.admin"
    # setIamPolicy está incluido en run.admin; se documenta por claridad
    warn "run.admin incluye run.services.setIamPolicy (necesario para --allow-unauthenticated)."
  fi

  cat <<EOF

${GREEN}Cloud Build SA configurada.${NC}

Permisos aplicados según pipelines:
  · cloudbuild.builds.builder   — ejecutar builds
  · artifactregistry.writer     — docker push (audio_to_mp3, onemarketer-api)
  · cloudfunctions.developer    — gcloud functions deploy --gen2
  · run.admin                   — Cloud Functions Gen2 / Cloud Run deploy
  · eventarc.admin              — trigger GCS en audio_to_mp3
  · storage.admin               — subir source code (onemarketer deploy por --source)
  · iam.serviceAccountUser      — actAs sobre SA runtime (si se indicó)

EOF
}

# --- main -------------------------------------------------------------------

PROFILE="${1:-}"
PROJECT_ID="${2:-}"
SA_EMAIL="${3:-}"
PUBLIC_INVOKER="false"
OAUTH_SECRET="${OAUTH_SECRET:-}"
RUNTIME_SA="${RUNTIME_SA:-}"

if [[ -z "${PROFILE}" || -z "${PROJECT_ID}" ]]; then
  usage
fi

if ! command -v gcloud &>/dev/null; then
  error "gcloud no está instalado."
  exit 1
fi

case "${PROFILE}" in
  discover)
    discover_accounts "${PROJECT_ID}"
    exit 0
    ;;

  runtime)
    if [[ -z "${SA_EMAIL}" ]]; then
      error "runtime requiere SA_EMAIL."
      usage
    fi
    shift 3
    ensure_gcloud_project "${PROJECT_ID}"
    validate_sa_exists "${PROJECT_ID}" "${SA_EMAIL}"
    BUCKET="${1:-${BUCKET:-}}"
    DATASET="${2:-${DATASET:-}}"
    OAUTH_SECRET="${3:-${OAUTH_SECRET:-}}"

    if [[ -z "${BUCKET}" || -z "${DATASET}" ]]; then
      warn "Recomendado indicar BUCKET y DATASET para IAM más restrictivo."
    fi

    apply_runtime_roles "${PROJECT_ID}" "${SA_EMAIL}" "${BUCKET}" "${DATASET}" "${OAUTH_SECRET}"
    ;;

  cloudbuild)
    shift 2
    SA_INPUT="default"
    if [[ -n "${1:-}" && "${1}" != --* ]]; then
      SA_INPUT="${1}"
      shift
    fi

    ensure_gcloud_project "${PROJECT_ID}"
    SA_EMAIL="$(resolve_cloudbuild_sa "${PROJECT_ID}" "${SA_INPUT}")"
    info "Cloud Build SA resuelta: ${SA_EMAIL}"
    validate_sa_exists "${PROJECT_ID}" "${SA_EMAIL}"

    for arg in "$@"; do
      case "${arg}" in
        --public-invoker) PUBLIC_INVOKER="true" ;;
        --runtime-sa=*)   RUNTIME_SA="${arg#*=}" ;;
        --runtime-sa)     shift; RUNTIME_SA="${1:-}" ;;
        *)
          if [[ -z "${RUNTIME_SA}" && "${arg}" != --* ]]; then
            RUNTIME_SA="${arg}"
          fi
          ;;
      esac
    done

    apply_cloudbuild_roles "${PROJECT_ID}" "${SA_EMAIL}" "${PUBLIC_INVOKER}" "${RUNTIME_SA}"
    ;;

  *)
    error "Perfil desconocido: ${PROFILE}. Usa 'runtime' o 'cloudbuild'."
    usage
    ;;
esac

info "Listo. Verifica con:"
echo "  gcloud projects get-iam-policy ${PROJECT_ID} \\"
echo "    --flatten='bindings[].members' \\"
echo "    --filter='bindings.members:serviceAccount:${SA_EMAIL}' \\"
echo "    --format='table(bindings.role)'"
