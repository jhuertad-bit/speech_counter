#!/bin/bash
# Script para probar la ejecución de un día específico con days_back = 0
# Uso: ./test_day.sh [YYYY-MM-DD]
# Si no se proporciona fecha, usa TODAY

set -e  # Salir si hay algún error

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Obtener el directorio del script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Cambiar al directorio del proyecto
cd "$PROJECT_DIR"

# Función para mostrar ayuda
show_help() {
    echo -e "${BLUE}Uso:${NC} $0 [YYYY-MM-DD]"
    echo ""
    echo "Ejemplos:"
    echo "  $0                    # Usa la fecha de hoy"
    echo "  $0 2025-12-01        # Procesa el día 2025-12-01"
    echo "  $0 TODAY              # Procesa la fecha de hoy"
    echo ""
    echo "Este script ejecuta el procesamiento para un día específico"
    echo "con days_back = 0 (solo procesa ese día, sin días anteriores)."
}

# Verificar argumentos
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# Obtener fecha
if [ -z "$1" ]; then
    # Si no se proporciona fecha, usar TODAY
    CURRENT_DATE="TODAY"
    echo -e "${YELLOW}No se proporcionó fecha, usando TODAY${NC}"
else
    CURRENT_DATE="$1"
fi

# Validar formato de fecha si no es TODAY
if [[ "$CURRENT_DATE" != "TODAY" ]]; then
    # Validar formato YYYY-MM-DD
    if ! [[ "$CURRENT_DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        echo -e "${RED}❌ Error: Formato de fecha inválido. Use YYYY-MM-DD${NC}"
        echo "Ejemplo: 2025-12-01"
        exit 1
    fi
    
    # Validar que la fecha sea válida (compatible con macOS y Linux)
    # Extraer año, mes y día
    YEAR=$(echo "$CURRENT_DATE" | cut -d'-' -f1)
    MONTH=$(echo "$CURRENT_DATE" | cut -d'-' -f2)
    DAY=$(echo "$CURRENT_DATE" | cut -d'-' -f3)
    
    # Validación básica de rangos
    if [ "$YEAR" -lt 2000 ] || [ "$YEAR" -gt 2100 ]; then
        echo -e "${RED}❌ Error: Año fuera de rango válido (2000-2100): $CURRENT_DATE${NC}"
        exit 1
    fi
    
    if [ "$MONTH" -lt 1 ] || [ "$MONTH" -gt 12 ]; then
        echo -e "${RED}❌ Error: Mes fuera de rango válido (01-12): $CURRENT_DATE${NC}"
        exit 1
    fi
    
    if [ "$DAY" -lt 1 ] || [ "$DAY" -gt 31 ]; then
        echo -e "${RED}❌ Error: Día fuera de rango válido (01-31): $CURRENT_DATE${NC}"
        exit 1
    fi
fi

# Configurar days_back = 0
DAYS_BACK=0

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Test de Ejecución - Un Día Específico${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Fecha:${NC} $CURRENT_DATE"
echo -e "${GREEN}Days Back:${NC} $DAYS_BACK"
echo -e "${GREEN}Directorio del proyecto:${NC} $PROJECT_DIR"
echo -e "${BLUE}========================================${NC}"
echo ""

# Verificar que existe main.py
if [ ! -f "$PROJECT_DIR/main.py" ]; then
    echo -e "${RED}❌ Error: No se encontró main.py en $PROJECT_DIR${NC}"
    exit 1
fi

# Verificar que existe config/config.json
if [ ! -f "$PROJECT_DIR/config/config.json" ]; then
    echo -e "${RED}❌ Error: No se encontró config/config.json${NC}"
    exit 1
fi

# Crear script Python temporal para ejecutar la función
TEMP_SCRIPT=$(mktemp)
cat > "$TEMP_SCRIPT" << EOF
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import sys
import os

# Agregar el directorio del proyecto al path
sys.path.insert(0, '$PROJECT_DIR')

from main import main

# Crear evento de prueba
event = {
    "current_date": "$CURRENT_DATE",
    "days_back": $DAYS_BACK
}

print("=" * 50)
print("INICIANDO PRUEBA")
print("=" * 50)
print(f"Evento: {json.dumps(event, indent=2)}")
print("=" * 50)
print("")

try:
    # Ejecutar la función main
    result = main(event)
    
    print("")
    print("=" * 50)
    print("RESULTADO DE LA PRUEBA")
    print("=" * 50)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("=" * 50)
    
    # Verificar el resultado
    if result.get('status') == 'success':
        print("")
        print("✅ PRUEBA EXITOSA")
        sys.exit(0)
    elif result.get('status') == 'partial_success':
        print("")
        print("⚠️  PRUEBA PARCIAL (algunas fechas fallaron)")
        sys.exit(1)
    else:
        print("")
        print("❌ PRUEBA FALLIDA")
        sys.exit(1)
        
except Exception as e:
    print("")
    print("=" * 50)
    print("ERROR EN LA PRUEBA")
    print("=" * 50)
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
EOF

# Hacer el script ejecutable
chmod +x "$TEMP_SCRIPT"

# Ejecutar el script Python
echo -e "${YELLOW}Ejecutando prueba...${NC}"
echo ""

if python3 "$TEMP_SCRIPT"; then
    echo ""
    echo -e "${GREEN}✅ Prueba completada exitosamente${NC}"
    EXIT_CODE=0
else
    echo ""
    echo -e "${RED}❌ La prueba falló${NC}"
    EXIT_CODE=1
fi

# Limpiar script temporal
rm -f "$TEMP_SCRIPT"

exit $EXIT_CODE

