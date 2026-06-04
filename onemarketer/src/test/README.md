# Carpeta de Pruebas

Esta carpeta contiene scripts para probar la ejecución del sistema de extracción de datos de OneMarketer.

## Medios de conversación (reporteChats + descargachats)

Flujo en la Cloud Function (y local vía `main.py`):

1. **getChats** (`reporteChats`) → `reporte_chats` en BigQuery.
2. Se marcan líneas **archivo** (mime audio/imagen/documento, etc.).
3. **descargachats** aporta la URL `download` por `idcase` + `idmessage`.
4. Descarga → GCS `utp_pregrado/whatsapp_documentos_raw/fecha_evento=.../`
5. Registro en `reporte_whatsapp_documento_raw` (misma tabla que `onemarketer_documentos`).

```bash
# Pipeline completo de un día (chats + medios)
python main.py   # o Cloud Function con current_date

# Solo medios, emparejando un JSONL ya extraído
python download_chat_media.py --fecha 2026-03-16 --from-jsonl reporteChats.jsonl
```

---

## Scripts Disponibles

### test_day.sh

Script para probar la ejecución de un día específico con `days_back = 0` (solo procesa ese día, sin días anteriores).

#### Uso

```bash
# Desde la raíz del proyecto
./test/test_day.sh [YYYY-MM-DD]
```

#### Ejemplos

```bash
# Procesar la fecha de hoy
./test/test_day.sh

# Procesar un día específico
./test/test_day.sh 2025-12-01

# Usar TODAY explícitamente
./test/test_day.sh TODAY
```

#### Parámetros

- **Sin parámetros**: Usa la fecha de hoy (TODAY)
- **YYYY-MM-DD**: Fecha específica a procesar (ej: 2025-12-01)
- **TODAY**: Procesa la fecha de hoy

#### Características

- ✅ Valida el formato de fecha
- ✅ Verifica que los archivos necesarios existan
- ✅ Muestra resultados detallados con colores
- ✅ Retorna códigos de salida apropiados para CI/CD
- ✅ Limpia archivos temporales automáticamente

#### Salida

El script muestra:
- Información de la prueba (fecha, days_back)
- Logs de ejecución del procesamiento
- Resultado final en formato JSON
- Estado de éxito/fallo

#### Códigos de Salida

- `0`: Prueba exitosa (todas las fechas procesadas correctamente)
- `1`: Prueba fallida (alguna fecha falló o hubo un error)

#### Requisitos

- Python 3
- Todas las dependencias del proyecto instaladas
- Archivo `config/config.json` configurado correctamente
- Credenciales de GCP configuradas (si se usa GCS/BigQuery)

---

### test_date_range.sh

Script para probar la ejecución de un intervalo de fechas con `days_back = 0`. Procesa cada día individualmente desde la fecha inicial hasta la fecha final.

#### Uso

```bash
# Desde la raíz del proyecto
./test/test_date_range.sh FECHA_INICIAL FECHA_FINAL
```

#### Ejemplos

```bash
# Procesar del 1 al 5 de diciembre de 2025
./test/test_date_range.sh 2025-12-01 2025-12-05

# Procesar todo enero de 2025
./test/test_date_range.sh 2025-01-01 2025-01-31

# Procesar una semana
./test/test_date_range.sh 2025-12-01 2025-12-07
```

#### Parámetros

- **FECHA_INICIAL**: Fecha de inicio en formato YYYY-MM-DD
- **FECHA_FINAL**: Fecha de fin en formato YYYY-MM-DD

**Nota**: La fecha inicial debe ser menor o igual a la fecha final.

#### Características

- ✅ Valida el formato de ambas fechas
- ✅ Valida que fecha inicial <= fecha final
- ✅ Procesa cada día individualmente con `days_back = 0`
- ✅ Muestra progreso en tiempo real
- ✅ Mantiene un resumen de éxitos y fallos
- ✅ Compatible con macOS y Linux
- ✅ Retorna códigos de salida apropiados para CI/CD
- ✅ Limpia archivos temporales automáticamente

#### Salida

El script muestra:
- Información del intervalo (fecha inicial, fecha final, número de días)
- Progreso para cada fecha procesada
- Resumen final con:
  - Total de fechas procesadas
  - Número de fechas exitosas
  - Número de fechas fallidas
  - Lista de fechas que fallaron (si las hay)

#### Códigos de Salida

- `0`: Todas las fechas se procesaron exitosamente
- `1`: Una o más fechas fallaron

#### Requisitos

- Python 3
- Todas las dependencias del proyecto instaladas
- Archivo `config/config.json` configurado correctamente
- Credenciales de GCP configuradas (si se usa GCS/BigQuery)

