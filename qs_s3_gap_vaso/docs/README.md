# qs_s3_gap_vaso

Cloud Run Job **aparte** de `qs_s3_to_gcs`. Solo backfill de audios que el ingest legado omitía:

1. Extensión **`.audio`**
2. Prefijo Ticketero con **len ≠ 6** (5 / 7+ típico)

Destino GCS: mismo path productivo. Catálogo: solo `hist_queesmart_mp3_catalog_vaso`.

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

## Deploy

Activador Cloud Build apuntando a `qs_s3_gap_vaso/cloudbuild.yaml` con `_JOB_NAME=prd-utpbi-s3-gap-vaso` y `_SOURCE_DIR=qs_s3_gap_vaso/src`.

## Ejecutar

```bash
JOB=prd-utpbi-s3-gap-vaso
DATE=2026-09-10

gcloud run jobs execute $JOB --region=us-central1 --project=prd-utpbi-data-operation --tasks=1 \
  --update-env-vars=QS_JOB_ROLE=gap_prepare,GAP_TARGET_DATE=$DATE

# N = candidates del meta del manifiesto
gcloud run jobs execute $JOB --region=us-central1 --project=prd-utpbi-data-operation --tasks=N \
  --update-env-vars=QS_JOB_ROLE=worker,SYNC_PROCESS_DATE=$DATE
```

Siguiente paso del pipeline vaso: `queuesmart_vaso` (consolidate → Whisper → analisis). Ver [queuesmart_vaso/README.md](../queuesmart_vaso/README.md).
