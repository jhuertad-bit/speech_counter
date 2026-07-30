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

El SP `sp_queuesmart_mp3_gen_ia` deja de llamar `ML.TRANSCRIBE` (o se retira del workflow).

## Manifiesto (GCS)

```
gs://prd-utp-stg-queuesmart/state/stt_manifests/2026-06-01.jsonl
gs://prd-utp-stg-queuesmart/state/stt_manifests/2026-06-01.meta.json
```

Cada línea JSONL ≈ fila enriched (gcs_uri + metadata de asesor/campus).

## Salida BQ

Mismas tablas que hoy usa el SP:

- `adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_raw`
- `adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_prd`

Campos clave:

- `transcripcion` — texto plano
- `transcripcion_con_hablantes` — `Persona 1: …\nPersona 2: …`
- `json_text` / `full_response` — JSON crudo STT
- `status` — `OK` o mensaje de error

## Environment variables

### Al desplegar el Job (`gcloud run jobs create|update --set-env-vars`)

Fijas en el contenedor. Lo demás (proyecto, bucket, tablas, modelo STT) va en `src/config/config.json`.

| Variable | Valor sugerido | Obligatoria | Descripción |
|----------|----------------|-------------|-------------|
| `CONFIG_PATH` | `/app/config/config.json` | Sí | Ruta al config dentro de la imagen |
| `PYTHONUNBUFFERED` | `1` | Recomendada | Logs sin buffer en Cloud Logging |

Ejemplo:

```bash
gcloud run jobs create prd-utpbi-qsmart-transcribe \
  --image=gcr.io/prd-utpbi-data-operation/prd-utpbi-qsmart-transcribe:latest \
  --region=us-central1 \
  --service-account=genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com \
  --set-env-vars="CONFIG_PATH=/app/config/config.json,PYTHONUNBUFFERED=1" \
  --parallelism=10 \
  --task-timeout=3600s \
  --memory=1Gi \
  --cpu=1 \
  --max-retries=1
```

La SA del Job necesita: Speech-to-Text, BigQuery (read enriched + write hist), Storage (manifiestos + lectura de audios GCS).

### En cada ejecución (inyecta el Workflow / `jobs execute`)

No hace falta fijarlas en el deploy: el workflow las manda en `containerOverrides.env`.

| Variable | Ejemplo | Obligatoria | Descripción |
|----------|---------|-------------|-------------|
| `QS_JOB_ROLE` | `prepare` \| `worker` | Sí | Rol de la corrida |
| `SYNC_PROCESS_DATE` | `2026-06-01` | Sí | Día a procesar (`YYYY-MM-DD`) |
| `SYNC_TARGET_DATE` | `2026-06-01` | No | Alias de `SYNC_PROCESS_DATE` (mismo valor) |

### Inyectadas por Cloud Run Jobs (no configurar)

| Variable | Descripción |
|----------|-------------|
| `CLOUD_RUN_TASK_INDEX` | Índice 0..N-1 de la task (elige la línea del manifiesto) |
| `CLOUD_RUN_TASK_COUNT` | Total de tasks de la ejecución |

## Prueba local (1 audio)

```bash
export QS_JOB_ROLE=worker
export CLOUD_RUN_TASK_INDEX=0
export CLOUD_RUN_TASK_COUNT=1
export SYNC_PROCESS_DATE=2026-06-01
# Requiere ADC + manifiesto ya generado por prepare
python src/main.py
```
