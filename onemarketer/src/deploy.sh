#!/bin/bash
# -*- coding: utf-8 -*-
# Despliegue manual vía gcloud functions deploy (alternativa local).
# En CI/CD usar: onemarketer/cloudbuild.yaml + scheduler-setup.sh
# Script de despliegue para Cloud Function OneMarketer
# Despliega la función con todas las configuraciones necesarias y opcionalmente configura el scheduler

set -e  # Salir si hay algún error

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Función para leer configuración desde config.json
load_config() {
    local config_file="config/config.json"
    
    if [[ ! -f "$config_file" ]]; then
        print_error "Archivo de configuración no encontrado: $config_file"
        exit 1
    fi
    
    # Usar jq para extraer valores del JSON
    if ! command -v jq &> /dev/null; then
        print_error "jq no está instalado. Instálalo para leer el archivo de configuración JSON"
        exit 1
    fi
    
    PROJECT_ID=$(jq -r '.gcp.project_id' "$config_file")
    REGION=$(jq -r '.gcp.region' "$config_file")
    FUNCTION_NAME=$(jq -r '.gcp.function_name' "$config_file")
    SCHEDULER_NAME=$(jq -r '.gcp.scheduler_name' "$config_file")
    SERVICE_ACCOUNT_NAME=$(jq -r '.gcp.service_account_name' "$config_file")
    DATASET_ID=$(jq -r '.gcp.dataset_id' "$config_file")
    BUCKET_NAME=$(jq -r '.gcp.bucket_name' "$config_file")

    # Overrides: prioridad env > config.json (mismo criterio que extract_chats.py)
    PROJECT_ID="${GCP_PROJECT_ID:-$PROJECT_ID}"
    REGION="${GCP_REGION:-$REGION}"
    FUNCTION_NAME="${GCP_FUNCTION_NAME:-$FUNCTION_NAME}"
    SCHEDULER_NAME="${GCP_SCHEDULER_NAME:-$SCHEDULER_NAME}"
    SERVICE_ACCOUNT_NAME="${GCP_SERVICE_ACCOUNT_NAME:-$SERVICE_ACCOUNT_NAME}"
    DATASET_ID="${GCP_DATASET_ID:-$DATASET_ID}"
    BUCKET_NAME="${GCP_BUCKET_NAME:-$BUCKET_NAME}"

    # Validar que todos los valores requeridos estén presentes
    if [[ -z "$PROJECT_ID" || "$PROJECT_ID" == "null" \
       || -z "$REGION" || "$REGION" == "null" \
       || -z "$FUNCTION_NAME" || "$FUNCTION_NAME" == "null" \
       || -z "$SCHEDULER_NAME" || "$SCHEDULER_NAME" == "null" \
       || -z "$SERVICE_ACCOUNT_NAME" || "$SERVICE_ACCOUNT_NAME" == "null" \
       || -z "$DATASET_ID" || "$DATASET_ID" == "null" \
       || -z "$BUCKET_NAME" || "$BUCKET_NAME" == "null" ]]; then
        print_error "Faltan valores GCP. Exporta GCP_PROJECT_ID, GCP_BUCKET_NAME, GCP_DATASET_ID, GCP_REGION, GCP_FUNCTION_NAME, GCP_SCHEDULER_NAME y GCP_SERVICE_ACCOUNT_NAME (config.json deja gcp vacío por ambiente)."
        exit 1
    fi
    
    print_info "Configuración cargada desde $config_file"
}

# Función para crear dataset de BigQuery
create_bigquery_dataset() {
    print_info "=== Creando dataset de BigQuery ==="
    print_info "Dataset: $DATASET_ID"
    print_info "Proyecto: $PROJECT_ID"
    print_info "Región: $REGION"
    
    # Habilitar API de BigQuery
    print_info "Habilitando API de BigQuery..."
    gcloud services enable bigquery.googleapis.com
    
    # Verificar si el dataset ya existe usando múltiples métodos
    print_info "Verificando si el dataset $DATASET_ID existe..."
    
    DATASET_EXISTS=false
    
    # Método 1: bq ls -d
    if bq ls -d --project_id="$PROJECT_ID" "$DATASET_ID" &> /dev/null; then
        DATASET_EXISTS=true
    fi
    
    # Método 2: bq show (más confiable)
    if ! $DATASET_EXISTS; then
        if bq show --project_id="$PROJECT_ID" "$DATASET_ID" &> /dev/null; then
            DATASET_EXISTS=true
        fi
    fi
    
    if $DATASET_EXISTS; then
        print_success "El dataset $DATASET_ID ya existe en el proyecto $PROJECT_ID"
        print_info "Continuando con el dataset existente..."
        
        # Intentar mostrar información del dataset existente (opcional)
        if DATASET_INFO=$(bq show --project_id="$PROJECT_ID" --format=json "$DATASET_ID" 2>/dev/null); then
            DATASET_LOCATION=$(echo "$DATASET_INFO" | jq -r '.location // "US"')
            print_info "Dataset existente encontrado:"
            print_info "  - ID: $DATASET_ID"
            print_info "  - Ubicación: $DATASET_LOCATION"
            print_info "  - Proyecto: $PROJECT_ID"
            
            # Verificar si la ubicación coincide
            if [[ "$DATASET_LOCATION" != "$REGION" ]]; then
                print_warning "La ubicación del dataset ($DATASET_LOCATION) no coincide con la región configurada ($REGION)"
                print_info "El dataset existente se mantendrá con su ubicación actual"
            fi
        else
            print_info "Dataset existente encontrado (información detallada no disponible)"
        fi
        
        print_success "Dataset de BigQuery verificado exitosamente"
    else
        print_info "El dataset $DATASET_ID no existe, creando nuevo dataset..."
        
        # Crear el dataset con la región especificada
        if bq mk --project_id="$PROJECT_ID" \
                 --location="$REGION" \
                 --description="Dataset para datos raw de OneMarketer - Reporte de Chats" \
                 "$DATASET_ID" 2>/dev/null; then
            print_success "Dataset de BigQuery creado exitosamente!"
            print_info "Dataset: $DATASET_ID"
            print_info "Proyecto: $PROJECT_ID"
            print_info "Región: $REGION"
        else
            # Verificar si el error es porque ya existe (race condition)
            if bq show --project_id="$PROJECT_ID" "$DATASET_ID" &> /dev/null; then
                print_success "Dataset $DATASET_ID ya existe (creado por otro proceso)"
                print_info "Continuando con el dataset existente..."
            else
                print_error "Error creando el dataset de BigQuery"
                print_error "Verifica permisos y configuración del proyecto"
                exit 1
            fi
        fi
    fi
    
    echo ""
    print_info "=== Comandos útiles de BigQuery ==="
    echo "Ver información del dataset:"
    echo "  bq show --project_id=$PROJECT_ID $DATASET_ID"
    echo ""
    echo "Listar tablas del dataset:"
    echo "  bq ls --project_id=$PROJECT_ID $DATASET_ID"
    echo ""
    echo "Eliminar dataset (¡CUIDADO!):"
    echo "  bq rm -r -f --project_id=$PROJECT_ID $DATASET_ID"
    echo ""
    echo "Ejecutar consulta SQL:"
    echo "  bq query --project_id=$PROJECT_ID --use_legacy_sql=false 'SELECT * FROM \`$PROJECT_ID.$DATASET_ID.reporte_chats\` LIMIT 10'"
    echo ""
}

# Función para imprimir mensajes con colores
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Configuración por defecto
FUNCTION_NAME="onemarketer-raw"
RUNTIME="python313"
REGION="us-central1"
MEMORY="2Gi"
TIMEOUT="3600s"
MAX_INSTANCES="10"
MIN_INSTANCES="0"
ENTRY_POINT="main"
GEN2="true"

# Configuración del scheduler (valores por defecto)
SCHEDULE="0 4 * * *"  # 4 AM todos los días
TIMEZONE="America/Lima"
PAYLOAD='{"current_date": "TODAY", "days_back": 3}'  # Procesa 3 días hacia atrás desde la fecha actual
# Por defecto, siempre crear/recrear el scheduler
CREATE_SCHEDULER=true

# Función para mostrar ayuda
show_help() {
    echo "Script de despliegue para Cloud Function OneMarketer"
    echo ""
    echo "Uso: $0"
    echo ""
    echo "El script toma toda la configuración desde config/config.json"
    echo "Solo ejecuta: $0"
    echo ""
    echo "El scheduler se crea automáticamente según la configuración en config.json"
}

# Cargar configuración desde config.json
if [[ -f "config/config.json" ]]; then
    load_config
else
    print_error "No se encontró config/config.json"
    print_error "Asegúrate de que el archivo config/config.json exista"
    exit 1
fi

# Validar que se proporcione el PROJECT_ID
if [[ -z "$PROJECT_ID" ]]; then
    print_error "No se encontró project_id en config/config.json"
    print_error "Asegúrate de que el archivo config/config.json contenga el campo 'gcp.project_id'"
    exit 1
fi

# Usar directorio actual
SOURCE_DIR="."

print_info "=== Despliegue de Cloud Function OneMarketer ==="
print_info "Configuración cargada desde config/config.json"
print_info "Función: $FUNCTION_NAME"
print_info "Proyecto: $PROJECT_ID"
print_info "Región: $REGION"
print_info "Dataset BigQuery: $DATASET_ID"
print_info "Bucket GCS: $BUCKET_NAME"
print_info "Runtime: $RUNTIME"
print_info "Generación: $([ "$GEN2" = "true" ] && echo "2da Generación" || echo "1ra Generación")"
print_info "Memoria: $MEMORY"
print_info "Timeout: $TIMEOUT"
print_info "Máx. instancias: $MAX_INSTANCES"
if [[ "$CREATE_SCHEDULER" == "true" ]]; then
    print_info "Scheduler: Se creará automáticamente ($SCHEDULER_NAME)"
else
    print_info "Scheduler: NO se creará (usar --no-scheduler para deshabilitar)"
fi
echo ""

# Verificar que gcloud esté instalado y configurado
print_info "Verificando gcloud CLI..."
if ! command -v gcloud &> /dev/null; then
    print_error "gcloud CLI no está instalado. Instálalo desde: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Verificar que bq esté instalado y configurado
print_info "Verificando bq CLI..."
if ! command -v bq &> /dev/null; then
    print_error "bq CLI no está instalado. Instálalo con: gcloud components install bq"
    exit 1
fi

# Verificar autenticación
print_info "Verificando autenticación..."
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    print_error "No hay cuentas autenticadas. Ejecuta: gcloud auth login"
    exit 1
fi

# Configurar proyecto
print_info "Configurando proyecto: $PROJECT_ID"
gcloud config set project "$PROJECT_ID"

# Habilitar APIs necesarias
print_info "Habilitando APIs necesarias..."
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable logging.googleapis.com
gcloud services enable run.googleapis.com
gcloud services enable eventarc.googleapis.com

# Crear dataset de BigQuery
create_bigquery_dataset

# Verificar que el directorio fuente existe
if [[ ! -d "$SOURCE_DIR" ]]; then
    print_error "El directorio fuente no existe: $SOURCE_DIR"
    exit 1
fi

# Verificar que main.py existe
if [[ ! -f "$SOURCE_DIR/main.py" ]]; then
    print_error "No se encontró main.py en el directorio fuente: $SOURCE_DIR"
    exit 1
fi

# Verificar que extract_chats.py existe
if [[ ! -f "$SOURCE_DIR/extract_chats.py" ]]; then
    print_error "No se encontró extract_chats.py en el directorio fuente: $SOURCE_DIR"
    exit 1
fi

# Verificar que config/config.json existe
if [[ ! -f "$SOURCE_DIR/config/config.json" ]]; then
    print_error "No se encontró config/config.json en el directorio fuente: $SOURCE_DIR"
    exit 1
fi


# Crear archivo .gcloudignore si no existe
if [[ ! -f "$SOURCE_DIR/.gcloudignore" ]]; then
    print_info "Creando archivo .gcloudignore..."
    cat > "$SOURCE_DIR/.gcloudignore" << EOF
# Archivos de desarrollo
*.pyc
__pycache__/
*.log
*.tmp
.DS_Store
.vscode/
.idea/

# Entornos virtuales
.venv/
venv/
env/

# Archivos de datos
*.jsonl
*.json
!config/config.json
!tablas/*.json

# Archivos de documentación
*.md
!cloud_function_usage.md

# Archivos de testing
test_*
*_test.py
test/

# Archivos de configuración local
.env
.env.local
EOF
    print_success "Archivo .gcloudignore creado"
fi

# Crear requirements.txt si no existe
if [[ ! -f "$SOURCE_DIR/requirements.txt" ]]; then
    print_info "Creando requirements.txt..."
    cat > "$SOURCE_DIR/requirements.txt" << EOF
requests>=2.28.0
google-cloud-storage>=2.7.0
google-cloud-bigquery>=3.10.0
EOF
    print_success "Archivo requirements.txt creado"
fi

# Desplegar la función
print_info "Desplegando Cloud Function..."
print_info "Esto puede tomar varios minutos..."

DEPLOY_SERVICE_ACCOUNT="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
GCP_ENV_VARS="GCP_PROJECT_ID=${PROJECT_ID},GCP_BUCKET_NAME=${BUCKET_NAME},GCP_DATASET_ID=${DATASET_ID},GCP_REGION=${REGION},GCP_FUNCTION_NAME=${FUNCTION_NAME},GCP_SCHEDULER_NAME=${SCHEDULER_NAME},GCP_SERVICE_ACCOUNT_NAME=${SERVICE_ACCOUNT_NAME},PYTHONUNBUFFERED=1"

if [[ "$GEN2" == "true" ]]; then
    # Cloud Functions de segunda generación
    print_info "Usando Cloud Functions de segunda generación..."
    gcloud functions deploy "$FUNCTION_NAME" \
        --gen2 \
        --runtime="$RUNTIME" \
        --trigger-http \
        --entry-point="$ENTRY_POINT" \
        --source="$SOURCE_DIR" \
        --region="$REGION" \
        --memory="$MEMORY" \
        --timeout="$TIMEOUT" \
        --max-instances="$MAX_INSTANCES" \
        --min-instances="$MIN_INSTANCES" \
        --allow-unauthenticated \
        --set-env-vars="$GCP_ENV_VARS" \
        --service-account="$DEPLOY_SERVICE_ACCOUNT" \
        --cpu="2" \
        --concurrency="80"
else
    # Cloud Functions de primera generación
    print_info "Usando Cloud Functions de primera generación..."
    gcloud functions deploy "$FUNCTION_NAME" \
        --runtime="$RUNTIME" \
        --trigger-http \
        --entry-point="$ENTRY_POINT" \
        --source="$SOURCE_DIR" \
        --region="$REGION" \
        --memory="$MEMORY" \
        --timeout="$TIMEOUT" \
        --max-instances="$MAX_INSTANCES" \
        --min-instances="$MIN_INSTANCES" \
        --allow-unauthenticated \
        --set-env-vars="PYTHONUNBUFFERED=1"
fi

# Verificar que el despliegue fue exitoso
if [[ $? -eq 0 ]]; then
    print_success "Cloud Function desplegada exitosamente!"
    
    # Obtener URL de la función
    if [[ "$GEN2" == "true" ]]; then
        FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --gen2 --format="value(serviceConfig.uri)")
    else
        FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --format="value(httpsTrigger.url)")
    fi
    
    echo ""
    print_info "=== Información de la función ==="
    print_info "Nombre: $FUNCTION_NAME"
    print_info "URL: $FUNCTION_URL"
    print_info "Región: $REGION"
    print_info "Proyecto: $PROJECT_ID"
    print_info "Generación: $([ "$GEN2" = "true" ] && echo "2da Generación" || echo "1ra Generación")"
    
    echo ""
    print_info "=== Comandos útiles ==="
    echo "Ver logs:"
    if [[ "$GEN2" == "true" ]]; then
        echo "  gcloud functions logs read $FUNCTION_NAME --region=$REGION --gen2 --limit=50"
    else
        echo "  gcloud functions logs read $FUNCTION_NAME --region=$REGION --limit=50"
    fi
    echo ""
    echo "Invocar función:"
    if [[ "$GEN2" == "true" ]]; then
        echo "  gcloud functions call $FUNCTION_NAME --region=$REGION --gen2 --data='{\"current_date\": \"2025-03-21\", \"days_back\": 3}'"
    else
        echo "  gcloud functions call $FUNCTION_NAME --region=$REGION --data='{\"current_date\": \"2025-03-21\", \"days_back\": 3}'"
    fi
    echo ""
    echo "Invocar vía HTTP:"
    echo "  curl -X POST $FUNCTION_URL -H 'Content-Type: application/json' -d '{\"current_date\": \"2025-03-21\", \"days_back\": 3}'"
    echo ""
    echo "Eliminar función:"
    if [[ "$GEN2" == "true" ]]; then
        echo "  gcloud functions delete $FUNCTION_NAME --region=$REGION --gen2"
    else
        echo "  gcloud functions delete $FUNCTION_NAME --region=$REGION"
    fi
    echo ""
    echo "BigQuery - Ver información del dataset:"
    echo "  bq show --project_id=$PROJECT_ID $DATASET_ID"
    echo ""
    echo "BigQuery - Listar tablas:"
    echo "  bq ls --project_id=$PROJECT_ID $DATASET_ID"
    echo ""
    echo "BigQuery - Ejecutar consulta:"
    echo "  bq query --project_id=$PROJECT_ID --use_legacy_sql=false 'SELECT * FROM \`$PROJECT_ID.$DATASET_ID.reporte_chats\` LIMIT 10'"
    
    echo ""
    print_success "¡Despliegue completado exitosamente!"
    
    # Configurar scheduler automáticamente
    if [[ "$CREATE_SCHEDULER" == "true" ]]; then
        echo ""
        print_info "=== Configurando Google Cloud Scheduler ==="
        
        # Configuración adicional del scheduler
        FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --gen2 --format="value(serviceConfig.uri)")
        SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
        
        print_info "Nombre del scheduler: $SCHEDULER_NAME"
        print_info "URL de la función: $FUNCTION_URL"
        print_info "Schedule: $SCHEDULE"
        print_info "Zona horaria: $TIMEZONE"
        print_info "Payload: $PAYLOAD"
        print_info "Service Account: $SERVICE_ACCOUNT_EMAIL"
        
        # Habilitar APIs necesarias para el scheduler
        print_info "Habilitando APIs necesarias para el scheduler..."
        gcloud services enable cloudscheduler.googleapis.com
        gcloud services enable iam.googleapis.com
        
        # La función ahora permite invocaciones no autenticadas, no se necesita service account
        print_info "La función permite invocaciones no autenticadas, no se requiere service account"
        
        # Siempre eliminar scheduler existente antes de crear uno nuevo
        print_warning "Eliminando scheduler existente..."
        if gcloud scheduler jobs describe "$SCHEDULER_NAME" --location="$REGION" &> /dev/null; then
            gcloud scheduler jobs delete "$SCHEDULER_NAME" --location="$REGION" --quiet
            print_success "Scheduler eliminado exitosamente"
        else
            print_info "No existe scheduler previo para eliminar"
        fi
        
        # Crear el scheduler job
        print_info "Creando Google Cloud Scheduler job..."
        print_info "Esto puede tomar unos minutos..."
        
        gcloud scheduler jobs create http "$SCHEDULER_NAME" \
            --location="$REGION" \
            --schedule="$SCHEDULE" \
            --time-zone="$TIMEZONE" \
            --uri="$FUNCTION_URL" \
            --http-method=POST \
            --headers="Content-Type=application/json" \
            --message-body="$PAYLOAD" \
            --description="Ejecuta Cloud Function onemarketer-raw diariamente a las 4 AM para procesar datos de reporteChats"
        
        # Verificar que el scheduler fue creado exitosamente
        if [[ $? -eq 0 ]]; then
            print_success "Google Cloud Scheduler job creado exitosamente!"
            
            echo ""
            print_info "=== Información del Scheduler ==="
            print_info "Nombre: $SCHEDULER_NAME"
            print_info "Proyecto: $PROJECT_ID"
            print_info "Región: $REGION"
            print_info "Schedule: $SCHEDULE"
            print_info "Zona horaria: $TIMEZONE"
            print_info "URL de destino: $FUNCTION_URL"
            print_info "Service Account: $SERVICE_ACCOUNT_EMAIL"
            
            echo ""
            print_info "=== Comandos útiles del Scheduler ==="
            echo "Ver detalles del scheduler:"
            echo "  gcloud scheduler jobs describe $SCHEDULER_NAME --location=$REGION"
            echo ""
            echo "Listar todos los schedulers:"
            echo "  gcloud scheduler jobs list --location=$REGION"
            echo ""
            echo "Ejecutar manualmente:"
            echo "  gcloud scheduler jobs run $SCHEDULER_NAME --location=$REGION"
            echo ""
            echo "Pausar el scheduler:"
            echo "  gcloud scheduler jobs pause $SCHEDULER_NAME --location=$REGION"
            echo ""
            echo "Reanudar el scheduler:"
            echo "  gcloud scheduler jobs resume $SCHEDULER_NAME --location=$REGION"
            echo ""
            echo "Eliminar el scheduler:"
            echo "  gcloud scheduler jobs delete $SCHEDULER_NAME --location=$REGION"
            echo ""
            echo "Ver logs del scheduler:"
            echo "  gcloud logging read 'resource.type=\"cloud_scheduler_job\" AND resource.labels.job_id=\"$SCHEDULER_NAME\"' --limit=50"
            
            echo ""
            print_success "¡Scheduler configurado exitosamente!"
            print_info "El job se ejecutará automáticamente según el schedule configurado ($SCHEDULE en $TIMEZONE)"
            
        else
            print_error "Error creando el Google Cloud Scheduler job"
            exit 1
        fi
    fi
    
else
    print_error "Error en el despliegue de la Cloud Function"
    exit 1
fi
