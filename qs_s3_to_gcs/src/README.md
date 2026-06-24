# s3_to_gcs

Micro-batch para copiar audios **MP3** desde un bucket **AWS S3** (QueeSmart) a **GCS**, organizados por **fecha en el nombre del archivo**.

## Convención de archivos S3

```
AAABBB-YYYYMMDD-correlativo.mp3
```

Ejemplo: `015AD1-20260217-123728.mp3`

| Parte | Significado |
|-------|-------------|
| `AAA` (`015`) | Código de campus |
| `BBB` (`AD1`) | Código de tipo (metadata) |
| `YYYYMMDD` | Fecha del audio |
| `correlativo` | ID secuencial / hora de grabación |

En GCS quedan bajo:

```
gs://{bucket}/{destination_prefix}/{YYYY-MM-DD}/{nombre_original}.mp3
```

Ejemplo:

```
gs://dev-utp-stg-queuesmart/data/input/queuesmart_mp3/imported_from_s3/2026-02-17/015AD1-20260217-123728.mp3
```

## Modos de sincronización

| Modo | Cuándo usar | Qué copia |
|------|-------------|-----------|
| `backfill_all` | Primera carga histórica | Todos los MP3 que coincidan con el patrón |
| `daily_last_n_days` | Prueba / ventana reciente | Últimos **N** días hasta ayer (`lookback_days`, default 15) |
| `daily_yesterday` | Scheduler diario | Solo archivos cuya fecha en el nombre = **ayer** (`America/Lima`) |

En ambos modos, si el blob ya existe en GCS se omite (`skip_if_exists_in_gcs: true`).

## Flujo

```
S3 (origen, lista plana)          GCS (destino por fecha)
015AD1-20260217-123728.mp3  -->   .../imported_from_s3/2026-02-17/015AD1-20260217-123728.mp3
        │                                    ▲
        │   Cloud Run Job (micro-batch)      │
        └──────── sync.py ───────────────────┘
                 state/s3_to_gcs_last_sync.json

Cloud Scheduler (diario 05:00 Lima) ──POST──► ejecuta el Cloud Run Job
```

## Características del micro-batch

- Filtra por **fecha en el nombre**, no por `LastModified` de S3.
- Organiza en carpetas `YYYY-MM-DD/` según esa fecha.
- Límite por corrida: `max_files` y `max_total_mb` (re-ejecutar hasta vaciar en backfill).
- Streaming S3 → GCS (sin disco local).
- Idempotente: no re-copia si el archivo ya está en GCS.

## Estructura

```
qs_s3_to_gcs/src/
├── config/config.json   # buckets, prefijos, modos, límites
├── audio_paths.py       # parser AAABBB-YYYYMMDD-*.mp3 y rutas GCS
├── sync.py              # lógica de copia
├── main.py              # entry point
├── Dockerfile
├── deploy.sh
├── setup-scheduler.sh
└── requirements.txt
```

## Configuración

Editar `config/config.json`:

| Sección | Clave | Descripción |
|---------|-------|-------------|
| `aws` | `bucket`, `prefix`, `region` | Origen S3 |
| `gcp` | `bucket_name`, `destination_prefix` | Destino GCS |
| `gcp` | `state_object` | Estado de corridas en GCS |
| `sync` | `mode` | `backfill_all`, `daily_last_n_days` o `daily_yesterday` |
| `sync` | `lookback_days` | Días hacia atrás en modo prueba (default `15`) |
| `sync` | `timezone` | Zona para calcular "ayer" (default `America/Lima`) |
| `sync` | `filename_regex` | Regex del nombre MP3 |
| `batch` | `max_files`, `max_total_mb` | Tope por ejecución |
| `gcp` | `schedule` | Cron (default `0 5 * * *` = 05:00 diario Lima) |

### Prueba — últimos 15 días

Config actual: `"mode": "daily_last_n_days", "lookback_days": 15`.

O por env sin redeploy:

```bash
gcloud run jobs execute dev-utpbi-s3-to-gcs-micro-batch \
  --region=us-central1 \
  --update-env-vars=SYNC_MODE=daily_last_n_days,SYNC_LOOKBACK_DAYS=15
```

Guía para volver a solo ayer: **[docs/sync-mode-switch.md](../docs/sync-mode-switch.md)**

### Primera carga (backfill)

1. Poner `"mode": "backfill_all"` en `config.json` **o** ejecutar el Job con env:

```bash
gcloud run jobs execute prd-utpbi-s3-to-gcs-micro-batch \
  --region=us-central1 \
  --update-env-vars=SYNC_MODE=backfill_all
```

2. Repetir la ejecución hasta que `copied: 0` y `already_in_gcs` cubra el resto (por límites de batch).
3. Cambiar a `"mode": "daily_yesterday"` y activar el scheduler.

### Scheduler diario (ayer)

Con `daily_yesterday`, cada corrida trae solo MP3 cuya fecha en el nombre sea el día anterior en `America/Lima`.

Para reprocesar un día concreto:

```bash
gcloud run jobs execute prd-utpbi-s3-to-gcs-micro-batch \
  --region=us-central1 \
  --update-env-vars=SYNC_MODE=daily_yesterday,SYNC_TARGET_DATE=2026-03-12
```

### Credenciales AWS (temporal: env vars)

Por permisos pendientes en Secret Manager, `secrets.source` está en **`env`**.

Configurar en el Cloud Run Job:

- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

Guía completa y pasos para volver a Secret Manager:
**[docs/aws-credentials-env-workaround.md](../docs/aws-credentials-env-workaround.md)**

> No guardar claves en el repo. Rotar en AWS si se expusieron fuera de Secret Manager.

## Variables de entorno (prioridad: env > config.json)

Igual que onemarketer: en Cloud Build / Cloud Run Job defines `GCP_*` y `AWS_*` por ambiente; el runtime las aplica sobre `config.json`.

### GCP (obligatorias en Cloud Build)

| Variable | Mapea a | Descripción |
|----------|---------|-------------|
| `GCP_PROJECT_ID` | `gcp.project_id` | Proyecto GCP |
| `GCP_BUCKET_NAME` | `gcp.bucket_name` | Bucket GCS destino |
| `GCP_DATASET_ID` | `gcp.dataset_id` / `bigquery.dataset_id` | Dataset BQ (`raw_queuesmart`) |
| `GCP_REGION` | `gcp.region` | Región Cloud Run / GCS (`us-central1`) |
| `GCP_JOB_NAME` | `gcp.cloud_run_job_name` | Nombre del Cloud Run Job |
| `GCP_SERVICE_ACCOUNT_EMAIL` | `gcp.service_account_email` | SA del job (email completo) |

### GCP (opcionales)

| Variable | Mapea a | Descripción |
|----------|---------|-------------|
| `GCP_SCHEDULER_NAME` | `gcp.scheduler_name` | Nombre del scheduler |
| `GCP_DESTINATION_PREFIX` | `gcp.destination_prefix` | Prefijo carpeta en GCS |
| `GCP_BQ_TABLE_ID` | `bigquery.table_id` | Tabla catálogo BQ |
| `GCP_BQ_LOCATION` | `bigquery.location` | Región dataset BQ |
| `GCP_AWS_SECRET_RESOURCE` | `secrets.secret_resource` | Ruta completa del secret AWS |

### AWS S3

| Variable | Mapea a | Descripción |
|----------|---------|-------------|
| `AWS_S3_BUCKET` | `aws.bucket` | Bucket origen |
| `AWS_S3_PREFIX` | `aws.prefix` | Prefijo en S3 |
| `AWS_REGION` | `aws.region` | Región AWS (`us-east-1`) |
| `AWS_ENDPOINT_URL` | `aws.endpoint_url` | Endpoint S3 |
| `AWS_ACCESS_KEY_ID` | — | Credencial (o Secret Manager) |
| `AWS_SECRET_ACCESS_KEY` | — | Credencial (o Secret Manager) |

### Sync (runtime)

| Variable | Mapea a | Descripción |
|----------|---------|-------------|
| `SYNC_MODE` | `sync.mode` | `backfill_all`, `daily_last_n_days` o `daily_yesterday` |
| `SYNC_LOOKBACK_DAYS` | `sync.lookback_days` | Ventana en modo prueba (ej. `15`) |
| `SYNC_TARGET_DATE` | `sync.target_date` | `YYYY-MM-DD` (reproceso manual) |

### Otras

| Variable | Descripción |
|----------|-------------|
| `CONFIG_PATH` | Ruta al config dentro del contenedor (default `/app/config/config.json`) |
| `PYTHONUNBUFFERED` | `1` — logs en tiempo real |

### Cloud Build — sustituciones obligatorias (activador)

```
_PROJECT_ID
_JOB_NAME
_SERVICE_ACCOUNT
_BUCKET_NAME
_DATASET_ID
_AWS_ACCESS_KEY_ID
_AWS_SECRET_ACCESS_KEY
```

Opcionales: `_AWS_S3_BUCKET`, `_AWS_ENDPOINT_URL`, `_GCP_DESTINATION_PREFIX`, `_SCHEDULER_NAME`, `_LOCATION`.

Las `_AWS_*` del activador se inyectan en el Job como `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`. Ver [docs/aws-credentials-env-workaround.md](../docs/aws-credentials-env-workaround.md).

## Despliegue

```bash
cd qs_s3_to_gcs/src
chmod +x deploy.sh setup-scheduler.sh
./deploy.sh
./setup-scheduler.sh   # después del backfill, con mode=daily_yesterday
```

Ejecutar el job a mano:

```bash
gcloud run jobs execute prd-utpbi-s3-to-gcs-micro-batch --region=us-central1
```

## Ejecución local

```bash
cd qs_s3_to_gcs/src
pip install -r requirements.txt
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export SYNC_MODE=backfill_all   # o daily_yesterday
python main.py
```

Salida JSON de resumen:

```json
{
  "status": "ok",
  "mode": "daily_yesterday",
  "target_date": "2026-03-12",
  "scanned": 5,
  "copied": 5,
  "skipped": 0,
  "already_in_gcs": 0,
  "bytes_copied": 5242880,
  "watermark_before": null,
  "watermark_after": "2026-03-12",
  "errors": []
}
```

## BigQuery — catálogo de archivos

Desplegar dataset y tabla (orden):

```bash
# 1. Dataset
bq query --use_legacy_sql=false < bigquery/datasets/raw_queuesmart.sql

# 2. Tabla catálogo (sustituir ${PROJECT_ID} y ${DATASET_RAW})
bq query --use_legacy_sql=false < bigquery/tables/hist_queesmart_mp3_catalog.sql
```

O dejar que el Cloud Run Job cree dataset/tabla en la primera corrida (`bq_catalog.py`).

Tras cada sync, el job registra metadatos en:

```
prd-utpbi-data-operation.raw_queuesmart.hist_queesmart_mp3_catalog
```

| Campo | Descripción |
|-------|-------------|
| `fecha_audio` | Fecha del audio (del nombre `YYYYMMDD`), partición |
| `fecha_procesamiento` | Cuándo corrió el job de sync |
| `file_name` | Nombre original (`015AD1-20260217-123728.mp3`) |
| `gcs_uri` | Ruta completa `gs://bucket/...` |
| `gcs_path` | Ruta dentro del bucket |
| `campus_code` | `AAA` del nombre |
| `type_code` | `BBB` del nombre |
| `correlative` | Correlativo del nombre |
| `s3_uri` / `s3_key` | Origen en S3 |
| `file_size_bytes` | Tamaño |
| `sync_mode` | `backfill_all` o `daily_yesterday` |

Idempotente: no duplica si el `gcs_uri` ya está en la tabla. En backfill, también cataloga archivos que ya existían en GCS (`catalog_existing_in_gcs: true`).

DDL manual (opcional):

```bash
# qs_s3_to_gcs/bigquery/tables/hist_queesmart_mp3_catalog.sql
```

IAM del Cloud Run Job: `roles/bigquery.dataEditor` en el dataset `raw_queuesmart`.

Consulta de ejemplo:

```sql
SELECT
  fecha_audio,
  campus_code,
  type_code,
  file_name,
  gcs_uri,
  file_size_bytes,
  fecha_procesamiento
FROM `prd-utpbi-data-operation.raw_queuesmart.hist_queesmart_mp3_catalog`
WHERE fecha_audio = DATE '2026-03-12'
ORDER BY file_name;
```

## Próximos pasos opcionales

- Subcarpetas por campus (`AAA/`) además de fecha.
- Disparar ETL downstream al terminar cada corrida.
