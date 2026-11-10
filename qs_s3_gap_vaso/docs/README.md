# qs_s3_gap_vaso

Cloud Run Job **aparte** de `qs_s3_to_gcs`. Solo backfill de audios que el ingest legado omitía:

1. Extensión **`.audio`**
2. Prefijo Ticketero con **len ≠ 6** (5 / 7+ típico)

Destino GCS: mismo path productivo. Catálogo: solo `hist_queesmart_mp3_catalog_vaso`.

Audio: mismo patrón que `qs_s3_to_gcs` (FLAC + loudnorm + split STT).

## Criterio

```
include = (ext == "audio") OR (len(prefix) != 6)
AND parseable (guiones)
AND fecha = GAP_TARGET_DATE
AND s3_key NOT IN (catalog prod ∪ catalog vaso)
AND no existe ya en GCS
```

## Setup BQ

```bash
bq query --use_legacy_sql=false --location=US \
  --project_id=prd-utpbi-data-operation \
  < qs_s3_gap_vaso/bigquery/tables/hist_queesmart_mp3_catalog_vaso.sql
```

(si el DDL está solo en monorepo, usa esa ruta).

## Deploy (Cloud Build — repo speech_counter)

Activador apuntando a `qs_s3_gap_vaso/cloudbuild.yaml` con `_JOB_NAME=prd-utpbi-s3-gap-vaso` y `_SOURCE_DIR=qs_s3_gap_vaso/src`.

```bash
# desde raíz speech_counter
gcloud builds submit --config=qs_s3_gap_vaso/cloudbuild.yaml \
  --project=prd-utpbi-data-operation .
```

## Ejecutar (manual)

```bash
JOB=prd-utpbi-s3-gap-vaso
DATE=2026-09-10

gcloud run jobs execute $JOB --region=us-central1 --project=prd-utpbi-data-operation --tasks=1 \
  --update-env-vars=QS_JOB_ROLE=gap_prepare,GAP_TARGET_DATE=$DATE

# N = candidates del meta del manifiesto
gcloud run jobs execute $JOB --region=us-central1 --project=prd-utpbi-data-operation --tasks=N \
  --update-env-vars=QS_JOB_ROLE=worker,SYNC_PROCESS_DATE=$DATE
```

## Downstream (STT, no Whisper)

Pipeline completo: `queuesmart_vaso` → consolidate → **`qsmart_transcribe`** → analisis.

```bash
gcloud builds submit --config=qsmart_transcribe/cloudbuild.yaml \
  --project=prd-utpbi-data-operation .

gcloud workflows deploy queuesmart-vaso-pipeline \
  --source=queuesmart_vaso/workflows/vaso_pipeline.yaml \
  --location=us-central1 --project=prd-utpbi-data-operation \
  --service-account=genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com
```

Detalle: [queuesmart_vaso/README.md](../queuesmart_vaso/README.md).
