#!/bin/bash
# Script para probar la ejecución de un intervalo de fechas con days_back = 0
# Uso: ./test_date_range.sh YYYY-MM-DD YYYY-MM-DD
# Procesa cada día individualmente desde la fecha inicial hasta la fecha final

set -e  # Salir si hay algún error

# Colores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Obtener el directorio del script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Cambiar al directorio del proyecto
cd "$PROJECT_DIR"

# Función para validar fecha
validate_date() {
    local date_str="$1"
    
    # Validar formato YYYY-MM-DD
    if ! [[ "$date_str" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        echo -e "${RED}❌ Error: Formato de fecha inválido. Use YYYY-MM-DD${NC}"
        echo "Ejemplo: 2025-12-01"
        return 1
    fi
    
    # Extraer año, mes y día
    local YEAR=$(echo "$date_str" | cut -d'-' -f1)
    local MONTH=$(echo "$date_str" | cut -d'-' -f2)
    local DAY=$(echo "$date_str" | cut -d'-' -f3)
    
    # Validación básica de rangos
    if [ "$YEAR" -lt 2000 ] || [ "$YEAR" -gt 2100 ]; then
        echo -e "${RED}❌ Error: Año fuera de rango válido (2000-2100): $date_str${NC}"
        return 1
    fi
    
    if [ "$MONTH" -lt 1 ] || [ "$MONTH" -gt 12 ]; then
        echo -e "${RED}❌ Error: Mes fuera de rango válido (01-12): $date_str${NC}"
        return 1
    fi
    
    if [ "$DAY" -lt 1 ] || [ "$DAY" -gt 31 ]; then
        echo -e "${RED}❌ Error: Día fuera de rango válido (01-31): $date_str${NC}"
        return 1
    fi
    
    return 0
}

# Función para comparar fechas (retorna 0 si fecha1 <= fecha2)
compare_dates() {
    local date1="$1"
    local date2="$2"
    
    # Convertir a formato comparable (YYYYMMDD)
    local d1=$(echo "$date1" | tr -d '-')
    local d2=$(echo "$date2" | tr -d '-')
    
    if [ "$d1" -le "$d2" ]; then
        return 0
    else
        return 1
    fi
}

# Función para obtener el siguiente día (compatible con macOS y Linux)
get_next_date() {
    local current_date="$1"
    local year=$(echo "$current_date" | cut -d'-' -f1)
    local month=$(echo "$current_date" | cut -d'-' -f2)
    local day=$(echo "$current_date" | cut -d'-' -f3)
    
    # Usar Python para calcular el siguiente día (compatible con ambos sistemas)
    python3 -c "
from datetime import datetime, timedelta
date = datetime.strptime('$current_date', '%Y-%m-%d')
next_date = date + timedelta(days=1)
print(next_date.strftime('%Y-%m-%d'))
"
}

# Función para mostrar ayuda
show_help() {
    echo -e "${BLUE}Uso:${NC} $0 FECHA_INICIAL FECHA_FINAL"
    echo ""
    echo "Ejemplos:"
    echo "  $0 2025-12-01 2025-12-05    # Procesa del 1 al 5 de diciembre de 2025"
    echo "  $0 2025-01-01 2025-01-31    # Procesa todo enero de 2025"
    echo ""
    echo "Este script ejecuta el procesamiento para cada día en el intervalo"
    echo "con days_back = 0 (solo procesa cada día individualmente)."
    echo ""
    echo "Parámetros:"
    echo "  FECHA_INICIAL  Fecha de inicio en formato YYYY-MM-DD"
    echo "  FECHA_FINAL    Fecha de fin en formato YYYY-MM-DD"
}

# Verificar argumentos
if [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# Validar que se proporcionen ambas fechas
if [ -z "$1" ] || [ -z "$2" ]; then
    echo -e "${RED}❌ Error: Se requieren dos fechas${NC}"
    echo ""
    show_help
    exit 1
fi

START_DATE="$1"
END_DATE="$2"

# Validar formato de fechas
if ! validate_date "$START_DATE"; then
    exit 1
fi

if ! validate_date "$END_DATE"; then
    exit 1
fi

# Validar que fecha inicial <= fecha final
if ! compare_dates "$START_DATE" "$END_DATE"; then
    echo -e "${RED}❌ Error: La fecha inicial debe ser menor o igual a la fecha final${NC}"
    echo -e "${RED}   Fecha inicial: $START_DATE${NC}"
    echo -e "${RED}   Fecha final: $END_DATE${NC}"
    exit 1
fi

# Configurar days_back = 0
DAYS_BACK=0

# Calcular número de días
NUM_DAYS=$(python3 -c "
from datetime import datetime
start = datetime.strptime('$START_DATE', '%Y-%m-%d')
end = datetime.strptime('$END_DATE', '%Y-%m-%d')
print((end - start).days + 1)
")

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Test de Ejecución - Intervalo de Fechas${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Fecha inicial:${NC} $START_DATE"
echo -e "${GREEN}Fecha final:${NC} $END_DATE"
echo -e "${GREEN}Días a procesar:${NC} $NUM_DAYS"
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

# Arrays para almacenar resultados
SUCCESSFUL_DATES=()
FAILED_DATES=()
TOTAL_SUCCESS=0
TOTAL_FAILED=0

# Función para procesar una fecha individual
process_single_date() {
    local date_to_process="$1"
    local current_num="$2"
    local total="$3"
    
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}[$current_num/$total] Procesando fecha: $date_to_process${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    # Crear script Python temporal para ejecutar la función
    local TEMP_SCRIPT=$(mktemp)
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
    "current_date": "$date_to_process",
    "days_back": $DAYS_BACK
}

try:
    # Ejecutar la función main
    result = main(event)
    
    # Verificar el resultado
    if result.get('status') == 'success':
        print("✅ ÉXITO")
        sys.exit(0)
    elif result.get('status') == 'partial_success':
        print("⚠️  PARCIAL (algunas fechas fallaron)")
        sys.exit(1)
    else:
        print("❌ FALLIDO")
        sys.exit(1)
        
except Exception as e:
    print(f"❌ ERROR: {e}")
    sys.exit(1)
EOF

    # Hacer el script ejecutable
    chmod +x "$TEMP_SCRIPT"
    
    # Ejecutar el script Python
    if python3 "$TEMP_SCRIPT" 2>&1; then
        SUCCESSFUL_DATES+=("$date_to_process")
        TOTAL_SUCCESS=$((TOTAL_SUCCESS + 1))
        echo -e "${GREEN}✅ Fecha $date_to_process procesada exitosamente${NC}"
        rm -f "$TEMP_SCRIPT"
        return 0
    else
        FAILED_DATES+=("$date_to_process")
        TOTAL_FAILED=$((TOTAL_FAILED + 1))
        echo -e "${RED}❌ Fecha $date_to_process falló${NC}"
        rm -f "$TEMP_SCRIPT"
        return 1
    fi
}

# Procesar cada fecha en el intervalo
CURRENT_DATE="$START_DATE"
CURRENT_NUM=1

while compare_dates "$CURRENT_DATE" "$END_DATE"; do
    process_single_date "$CURRENT_DATE" "$CURRENT_NUM" "$NUM_DAYS"
    
    # Obtener siguiente fecha
    if [ "$CURRENT_DATE" != "$END_DATE" ]; then
        CURRENT_DATE=$(get_next_date "$CURRENT_DATE")
    else
        break
    fi
    
    CURRENT_NUM=$((CURRENT_NUM + 1))
done

# Mostrar resumen final
echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  RESUMEN FINAL${NC}"
echo -e "${BLUE}========================================${NC}"
echo -e "${GREEN}Total de fechas procesadas:${NC} $NUM_DAYS"
echo -e "${GREEN}Exitosas:${NC} $TOTAL_SUCCESS"
echo -e "${RED}Fallidas:${NC} $TOTAL_FAILED"
echo ""

if [ $TOTAL_FAILED -eq 0 ]; then
    echo -e "${GREEN}✅ Todas las fechas se procesaron exitosamente${NC}"
    EXIT_CODE=0
else
    echo -e "${YELLOW}⚠️  Algunas fechas fallaron:${NC}"
    for failed_date in "${FAILED_DATES[@]}"; do
        echo -e "  ${RED}❌ $failed_date${NC}"
    done
    EXIT_CODE=1
fi

echo ""
echo -e "${BLUE}========================================${NC}"

exit $EXIT_CODE

