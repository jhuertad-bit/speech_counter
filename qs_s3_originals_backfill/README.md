# Backfill one-shot: originales Ticketero S3 → GCS + UPDATE hist_queesmart_mp3_catalog

Job Cloud Run paralelo (prepare / worker), mismo patrón que `qs_s3_to_gcs` / `promotores_gcs_copy`.

## Qué hace

1. **prepare** — consulta BQ filas con `gcs_original_path` vacío en un rango de `fecha_audio`, escribe manifiesto en GCS.
2. **worker** — por task: copia `s3://…/{s3_key}` → `gs://…/{fecha}/original/{source_file_name}` y hace `UPDATE` de `gcs_original_uri` / `gcs_original_path`.

Sin ffmpeg (solo copia). Idempotente: si el blob ya existe, solo actualiza BQ.

## Pre-requisito

```bash
bq query --use_legacy_sql=false --location=US \
  < qs_s3_to_gcs/bigquery/sqls/alter_gcs_original_path.sql
```

## Deploy (Cloud Build)

Desde la raíz del monorepo / `speech_counter` (donde vive el activador):

Sustituciones típicas PRD: `_PROJECT_ID=prd-utpbi-data-operation`, `_JOB_NAME=prd-utpbi-s3-originals-backfill`, `_SERVICE_ACCOUNT=genesys-audio-processor@…`, `_BUCKET_NAME=prd-utp-stg-queuesmart`, `_DATASET_ID=raw_queue_smart`, `_AWS_S3_BUCKET`, `_AWS_*` keys, `_SOURCE_DIR=qs_s3_originals_backfill/src`, `_PARALLELISM=20`.

## Ejecución (una vez por rango)

```bash
# Prepare
gcloud run jobs execute prd-utpbi-s3-originals-backfill \
  --region=us-central1 --project=prd-utpbi-data-operation \
  --tasks=1 \
  --update-env-vars=JOB_ROLE=prepare,BACKFILL_START_DATE=2026-07-01,BACKFILL_END_DATE=2026-08-31

# Leer count
# gs://prd-utp-stg-queuesmart/state/manifests_originals_backfill/2026-07-01_2026-08-31.meta.json

# Worker (N = count)
gcloud run jobs execute prd-utpbi-s3-originals-backfill \
  --region=us-central1 --project=prd-utpbi-data-operation \
  --tasks=N \
  --update-env-vars=JOB_ROLE=worker,BACKFILL_START_DATE=2026-07-01,BACKFILL_END_DATE=2026-08-31
```

El `process_date` del manifiesto es `{start}_{end}` (ej. `2026-07-01_2026-08-31`).

## Rutas

| Tipo | Path |
|------|------|
| FLAC (ya existente) | `queuesmart_mp3_s3/{YYYY-MM-DD}/{stem}.flac` |
| Original (este job) | `queuesmart_mp3_s3/{YYYY-MM-DD}/original/{source_file_name}` |

`source_file_name` en BQ sigue siendo solo el basename (join tickets).
