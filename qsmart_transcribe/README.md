# qsmart_transcribe — Cloud Run Job (STT Chirp 3 + diarización)

Reemplaza `ML.TRANSCRIBE` de BigQuery. Usa **Speech-to-Text API v2** (`chirp_3` + speaker diarization).

## Roles (`QS_JOB_ROLE`)

| Rol | Tasks | Qué hace |
|-----|-------|----------|
| `prepare` | 1 | Lee URIs del día en BQ (`queuesmart_mp3_enriched`) → manifiesto JSONL + meta en GCS |
| `worker` | N (= count) | `CLOUD_RUN_TASK_INDEX` toma 1 línea → STT v2 → escribe hist raw/prd |

## Paralelismo

Igual que `qs_s3_to_gcs`:

1. Workflow corre prepare (`taskCount=1`).
2. Lee `state/stt_manifests/{date}.meta.json` → `count`.
3. Corre worker con `taskCount=count` y `parallelism` del Job (p. ej. 10–20).
4. Cada task procesa **1 audio**.

## Flujo en el pipeline

```
S3→GCS Job → consolidate (BQ)
           → qsmart_transcribe prepare/worker   ← NUEVO (en lugar de sp_queuesmart_mp3_gen_ia STT)
           → analisis Gemini (BQ)
```

## Deploy (Cloud Build)

Archivos:

- `cloudbuild.yaml`
- `scripts/cloudbuild_deploy.sh`

En el activador de Cloud Build, configurar **Variables de sustitución** (mismo estilo que `qs_s3_to_gcs`).

### Obligatorias (activador)

| Variable | Ejemplo prd | Descripción |
|----------|-------------|-------------|
| `_PROJECT_ID` | `prd-utpbi-data-operation` | Proyecto GCP |
| `_JOB_NAME` | `prd-utpbi-qsmart-transcribe` | Nombre del Cloud Run Job |
| `_SERVICE_ACCOUNT` | `genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com` | SA del Job (email completo) |
| `_BUCKET_NAME` | `prd-utp-stg-queuesmart` | Bucket GCS (audios + manifiestos STT) |

### Opcionales (defaults en `cloudbuild.yaml`)

| Variable | Default | Descripción |
|----------|---------|-------------|
| `_LOCATION` | `us-central1` | Región Cloud Run |
| `_SOURCE_DIR` | `qsmart_transcribe/src` | Contexto del Dockerfile |
| `_MEMORY` | `1Gi` | Memoria por task |
| `_CPU` | `1` | CPU por task |
| `_TASK_TIMEOUT` | `3600s` | Timeout por task |
| `_MAX_RETRIES` | `1` | Reintentos por task |
| `_PARALLELISM` | `10` | Tasks concurrentes del Job |
| `_CONFIG_PATH` | `/app/config/config.json` | Config dentro del contenedor |
| `_STT_LOCATION` | `us` | Región API Speech (`us` / `eu`) |
| `_STT_MODEL` | `chirp_3` | Modelo STT |
| `_MANIFEST_PREFIX` | `state/stt_manifests` | Prefijo GCS del manifiesto |
| `_BQ_LOCATION` | `US` | Location BigQuery |
| `_ENRICHED_TABLE` | `…raw_queue_smart.queuesmart_mp3_enriched` | Tabla fuente URIs |
| `_HIST_RAW_TABLE` | `…hist_queuesmart_mp3_gen_ia_process_data_raw` | Destino raw |
| `_HIST_PRD_TABLE` | `…hist_queuesmart_mp3_gen_ia_process_data_prd` | Destino prd |

### Env vars que el deploy escribe en el Job

El script traduce las sustituciones a env del contenedor (`env > config.json`):

| Env en el Job | Viene de |
|---------------|----------|
| `CONFIG_PATH` | `_CONFIG_PATH` |
| `PYTHONUNBUFFERED` | fijo `1` |
| `GCP_PROJECT_ID` | `_PROJECT_ID` |
| `GCP_BUCKET_NAME` | `_BUCKET_NAME` |
| `GCP_REGION` | `_LOCATION` |
| `GCP_JOB_NAME` | `_JOB_NAME` |
| `GCP_SERVICE_ACCOUNT_EMAIL` | `_SERVICE_ACCOUNT` |
| `GCP_STT_LOCATION` | `_STT_LOCATION` |
| `GCP_BQ_LOCATION` | `_BQ_LOCATION` |
| `QS_STT_MODEL` | `_STT_MODEL` |
| `QS_MANIFEST_PREFIX` | `_MANIFEST_PREFIX` |
| `QS_ENRICHED_TABLE` | `_ENRICHED_TABLE` |
| `QS_HIST_RAW_TABLE` | `_HIST_RAW_TABLE` |
| `QS_HIST_PRD_TABLE` | `_HIST_PRD_TABLE` |

La SA necesita: Speech-to-Text, BigQuery (read enriched + write hist), Storage (manifiestos + lectura de audios).

### En cada ejecución (inyecta el Workflow)

| Variable | Ejemplo | Descripción |
|----------|---------|-------------|
| `QS_JOB_ROLE` | `prepare` \| `worker` | Rol de la corrida |
| `SYNC_PROCESS_DATE` | `2026-06-01` | Día a procesar |
| `SYNC_TARGET_DATE` | `2026-06-01` | Alias opcional |

### Inyectadas por Cloud Run (no configurar)

| Variable | Descripción |
|----------|-------------|
| `CLOUD_RUN_TASK_INDEX` | Índice 0..N-1 (línea del manifiesto) |
| `CLOUD_RUN_TASK_COUNT` | Total de tasks |

## Manifiesto (GCS)

```
gs://prd-utp-stg-queuesmart/state/stt_manifests/2026-06-01.jsonl
gs://prd-utp-stg-queuesmart/state/stt_manifests/2026-06-01.meta.json
```

## Salida BQ

- `adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_raw`
- `adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_prd`

Campos clave: `transcripcion`, `transcripcion_con_hablantes` (`Persona 1:` / `Persona 2:`), `json_text`, `status`.

## Prueba local (1 audio)

```bash
export QS_JOB_ROLE=worker
export CLOUD_RUN_TASK_INDEX=0
export CLOUD_RUN_TASK_COUNT=1
export SYNC_PROCESS_DATE=2026-06-01
python src/main.py
```
