#!/usr/bin/env bash
# Deploy onemarketer-api como Cloud Function Gen2 (reemplaza el recurso existente).
# - NO toca IAM por defecto (evita 403 run.services.setIamPolicy).
# - OAuth: _OAUTH_SECRET (Secret Manager) O bien _OAUTH_USER + _OAUTH_PASSWORD (env).
set -euo pipefail

missing=0
require() {
  local name="$1"
  local value="$2"
  if [[ -z "${value}" ]]; then
    echo "ERROR: falta ${name} — Variables de sustitución del activador Cloud Build." >&2
    missing=1
  else
    echo "OK ${name}=${value}"
  fi
}

trim() { local v="${1:-}"; v="${v#"${v%%[![:space:]]*}"}"; v="${v%"${v##*[![:space:]]}"}"; printf '%s' "$v"; }

_PROJECT_ID="$(trim "${_PROJECT_ID:-}")"
_FUNCTION_NAME="$(trim "${_FUNCTION_NAME:-}")"
_SERVICE_ACCOUNT="$(trim "${_SERVICE_ACCOUNT:-}")"
_BUCKET_NAME="$(trim "${_BUCKET_NAME:-}")"
_DATASET_ID="$(trim "${_DATASET_ID:-}")"
_OAUTH_SECRET="$(trim "${_OAUTH_SECRET:-}")"
_OAUTH_USER="$(trim "${_OAUTH_USER:-}")"
_OAUTH_PASSWORD="$(trim "${_OAUTH_PASSWORD:-}")"
_LOCATION="$(trim "${_LOCATION:-}")"
_REPO_NAME="$(trim "${_REPO_NAME:-}")"
_MEMORY="$(trim "${_MEMORY:-}")"
_TIMEOUT="$(trim "${_TIMEOUT:-}")"
_CPU="$(trim "${_CPU:-}")"
_MAX_INSTANCES="$(trim "${_MAX_INSTANCES:-}")"
_CONCURRENCY="$(trim "${_CONCURRENCY:-}")"
_ALLOW_UNAUTHENTICATED="$(trim "${_ALLOW_UNAUTHENTICATED:-}")"
_SOURCE_DIR="$(trim "${_SOURCE_DIR:-}")"
_SCHEDULER_NAME="$(trim "${_SCHEDULER_NAME:-}")"
_SERVICE_ACCOUNT_NAME="$(trim "${_SERVICE_ACCOUNT_NAME:-}")"

echo "=== Validando variables del activador ==="
require "_PROJECT_ID" "${_PROJECT_ID}"
require "_FUNCTION_NAME" "${_FUNCTION_NAME}"
require "_SERVICE_ACCOUNT" "${_SERVICE_ACCOUNT}"
require "_BUCKET_NAME" "${_BUCKET_NAME}"
require "_DATASET_ID" "${_DATASET_ID}"
if [[ -n "${_SERVICE_ACCOUNT}" && "${_SERVICE_ACCOUNT}" != *"@"* ]]; then
  echo "ERROR: _SERVICE_ACCOUNT debe ser email completo" >&2
  missing=1
fi

# OAuth: secreto SM O pair user/password (si no pueden crear secretos)
if [[ -n "${_OAUTH_SECRET}" ]]; then
  echo "OK _OAUTH_SECRET=${_OAUTH_SECRET}"
elif [[ -n "${_OAUTH_USER}" && -n "${_OAUTH_PASSWORD}" ]]; then
  echo "OK _OAUTH_USER=${_OAUTH_USER} (password via env, sin Secret Manager)"
else
  echo "ERROR: configura _OAUTH_SECRET O bien (_OAUTH_USER + _OAUTH_PASSWORD)." >&2
  echo "  Sin permiso para crear secretos → usa _OAUTH_USER / _OAUTH_PASSWORD en el activador." >&2
  missing=1
fi

if [[ "${missing}" -ne 0 ]]; then
  exit 1
fi

LOCATION="${_LOCATION:-us-central1}"
REPO_NAME="${_REPO_NAME:-gcf-artifacts}"
MEMORY="${_MEMORY:-512Mi}"
TIMEOUT="${_TIMEOUT:-540s}"
CPU="${_CPU:-1}"
MAX_INSTANCES="${_MAX_INSTANCES:-10}"
CONCURRENCY="${_CONCURRENCY:-1}"
# false por defecto: no llama setIamPolicy (403 si Cloud Build SA no tiene run.admin IAM)
ALLOW_UNAUTH="${_ALLOW_UNAUTHENTICATED:-false}"
SOURCE_DIR="${_SOURCE_DIR:-onemarketer-api/src}"

if [[ ! -f "${SOURCE_DIR}/Dockerfile" ]]; then
  echo "ERROR: falta Dockerfile en ${SOURCE_DIR}" >&2
  exit 1
fi
if [[ ! -f "${SOURCE_DIR}/main.py" ]]; then
  echo "ERROR: falta main.py en ${SOURCE_DIR}" >&2
  exit 1
fi

ENV_VARS="PYTHONUNBUFFERED=1"
ENV_VARS+=",GCP_PROJECT_ID=${_PROJECT_ID}"
ENV_VARS+=",GCP_BUCKET_NAME=${_BUCKET_NAME}"
ENV_VARS+=",GCP_DATASET_ID=${_DATASET_ID}"
ENV_VARS+=",GCP_REGION=${LOCATION}"
ENV_VARS+=",GCP_SERVICE_NAME=${_FUNCTION_NAME}"
ENV_VARS+=",GCP_SERVICE_ACCOUNT_EMAIL=${_SERVICE_ACCOUNT}"
if [[ -n "${_SCHEDULER_NAME}" ]]; then
  ENV_VARS+=",GCP_SCHEDULER_NAME=${_SCHEDULER_NAME}"
fi
if [[ -n "${_SERVICE_ACCOUNT_NAME}" ]]; then
  ENV_VARS+=",GCP_SERVICE_ACCOUNT_NAME=${_SERVICE_ACCOUNT_NAME}"
fi
if [[ -z "${_OAUTH_SECRET}" ]]; then
  ENV_VARS+=",ONEMARKETER_OAUTH_USER=${_OAUTH_USER}"
  ENV_VARS+=",ONEMARKETER_OAUTH_PASSWORD=${_OAUTH_PASSWORD}"
fi

echo "=== Habilitando APIs ==="
gcloud services enable cloudfunctions.googleapis.com run.googleapis.com \
  cloudbuild.googleapis.com bigquery.googleapis.com storage.googleapis.com \
  --project="${_PROJECT_ID}" --quiet

DEPLOY_ARGS=(
  functions deploy "${_FUNCTION_NAME}"
  --gen2
  --project="${_PROJECT_ID}"
  --region="${LOCATION}"
  --runtime=python310
  --source="${SOURCE_DIR}"
  --entry-point=main
  --trigger-http
  --memory="${MEMORY}"
  --timeout="${TIMEOUT}"
  --cpu="${CPU}"
  --max-instances="${MAX_INSTANCES}"
  --concurrency="${CONCURRENCY}"
  --service-account="${_SERVICE_ACCOUNT}"
  --set-env-vars="${ENV_VARS}"
)

if [[ -n "${_OAUTH_SECRET}" ]]; then
  DEPLOY_ARGS+=(--set-secrets="ONEMARKETER_API_CREDENTIALS=${_OAUTH_SECRET}:latest")
fi

if [[ -n "${REPO_NAME}" ]]; then
  DEPLOY_ARGS+=(
    "--docker-repository=${LOCATION}-docker.pkg.dev/${_PROJECT_ID}/${REPO_NAME}"
  )
fi

if [[ "${ALLOW_UNAUTH}" == "true" ]]; then
  echo "Modo público: --allow-unauthenticated (requiere run.services.setIamPolicy)"
  DEPLOY_ARGS+=(--allow-unauthenticated)
else
  echo "Sin tocar IAM (default). Schedulers existentes siguen con la policy actual."
fi

echo "=== gcloud functions deploy ${_FUNCTION_NAME} (source: ${SOURCE_DIR}) ==="
echo "Esto REEMPLAZA la Cloud Function Gen2 existente con el mismo nombre."
gcloud "${DEPLOY_ARGS[@]}"

URI="$(gcloud functions describe "${_FUNCTION_NAME}" \
  --project="${_PROJECT_ID}" \
  --region="${LOCATION}" \
  --gen2 \
  --format='value(serviceConfig.uri)' 2>/dev/null || true)"

echo "=== Deploy OK ==="
echo "Function: ${_FUNCTION_NAME}"
echo "URI: ${URI}"
echo "Probar (si la policy permite allUsers o tu identity):"
echo "  curl -sS -X POST '${URI}' -H 'Content-Type: application/json' \\"
echo "    -d '{\"current_date\":\"TODAY\",\"days_back\":0}'"
