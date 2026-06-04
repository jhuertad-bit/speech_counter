#!/bin/bash

# Script de despliegue para OneMarketer API Cloud Function Gen 2 (Versión Corregida)

set -e

echo "=== Desplegando OneMarketer API Cloud Function (Gen 2) ==="

# Verificar que estamos en el directorio correcto
if [ ! -f "main.py" ]; then
    echo "Error: No se encontró main.py. Ejecutar desde el directorio del proyecto."
    exit 1
fi

# Verificar que gcloud está instalado
if ! command -v gcloud &> /dev/null; then
    echo "Error: gcloud CLI no está instalado o no está en el PATH"
    exit 1
fi

# Configuración
FUNCTION_NAME="onemarketer-api"
RUNTIME="python312"
REGION="us-central1"
MEMORY="512MiB"
TIMEOUT="540s"
MAX_INSTANCES="10"

echo "Configuración:"
echo "  - Función: $FUNCTION_NAME"
echo "  - Generación: Gen 2"
echo "  - Runtime: $RUNTIME"
echo "  - Región: $REGION"
echo "  - Memoria: $MEMORY"
echo "  - Timeout: $TIMEOUT"
echo "  - Máx. instancias: $MAX_INSTANCES"
echo ""

# Verificar autenticación
echo "Verificando autenticación de Google Cloud..."
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q .; then
    echo "Error: No hay cuentas autenticadas en gcloud"
    echo "Ejecutar: gcloud auth login"
    exit 1
fi

# Obtener proyecto actual
PROJECT_ID=$(gcloud config get-value project)
if [ -z "$PROJECT_ID" ]; then
    echo "Error: No hay proyecto configurado en gcloud"
    echo "Ejecutar: gcloud config set project PROJECT_ID"
    exit 1
fi

echo "Proyecto actual: $PROJECT_ID"
echo ""

# Verificar que el proyecto existe
if ! gcloud projects describe "$PROJECT_ID" &> /dev/null; then
    echo "Error: El proyecto $PROJECT_ID no existe o no tienes acceso"
    exit 1
fi

# Habilitar APIs necesarias
echo "Habilitando APIs necesarias..."
gcloud services enable cloudfunctions.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable storage.googleapis.com
gcloud services enable bigquery.googleapis.com
gcloud services enable run.googleapis.com  # Necesario para Gen 2

# Limpiar archivos temporales que puedan causar problemas
echo "Limpiando archivos temporales..."
rm -rf .venv
rm -rf __pycache__
rm -rf */__pycache__
rm -rf .gcloudignore

# Crear .gcloudignore para evitar problemas
echo "Creando .gcloudignore..."
cat > .gcloudignore << EOF
# This file specifies files that are *not* uploaded to Google Cloud
# using gcloud. It follows the same syntax as .gitignore, with the addition of
# "#!include" directives (which insert the entries of the given .gitignore-style
# file at that point).

.gcloudignore
# If you would like to upload your .git directory, .gitignore file or files
# from your .gitignore file, remove the corresponding line below:
.git
.gitignore

# Python pycache:
__pycache__/
*.py[cod]
*$py.class

# Distribution / packaging
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Virtual environments
.env
.venv
env/
venv/
ENV/
env.bak/
venv.bak/

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Test files
test_*.py
*_test.py
tests/

# Logs
*.log
EOF

# Desplegar la función (Cloud Functions Gen 2)
echo ""
echo "Desplegando Cloud Function (Gen 2)..."
gcloud functions deploy "$FUNCTION_NAME" \
    --gen2 \
    --runtime="$RUNTIME" \
    --trigger-http \
    --allow-unauthenticated \
    --region="$REGION" \
    --memory="$MEMORY" \
    --timeout="$TIMEOUT" \
    --max-instances="$MAX_INSTANCES" \
    --source=. \
    --entry-point=main

# Obtener URL de la función (Gen 2)
echo ""
echo "Obteniendo URL de la función..."
FUNCTION_URL=$(gcloud functions describe "$FUNCTION_NAME" --region="$REGION" --gen2 --format="value(serviceConfig.uri)")

echo ""
echo "=== Despliegue completado exitosamente ==="
echo "URL de la función: $FUNCTION_URL"
echo ""
echo "Ejemplo de uso:"
echo "curl -X POST '$FUNCTION_URL' \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -d '{\"current_date\": \"2025-01-15\", \"days_back\": 0}'"
echo ""
echo "Para probar localmente:"
echo "python3 test_function.py"
echo ""
echo "Para ver logs:"
echo "gcloud functions logs read $FUNCTION_NAME --region=$REGION --gen2"
