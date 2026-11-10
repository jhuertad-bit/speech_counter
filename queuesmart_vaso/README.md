# queuesmart_vaso (speech_counter)

Orquestación del pipeline VASO QueeSmart. **Fuente de deploy = este repo** (`speech_counter`), no el monorepo.

## Flujo

```
qs_s3_gap_vaso (FLAC listo para STT)
  → consolidate_vaso
  → prd-utpbi-qsmart-transcribe prepare/worker → hist_*_whisper_vaso_*
  → analisis_ia_vaso
```

Las tablas `*_whisper_vaso_*` mantienen el nombre histórico; el productor es **STT Chirp** (`qsmart_transcribe`). No toca tablas prod.

| Etapa | Paquete / Job | Cloud Build |
|---|---|---|
| Ingest S3 | `qs_s3_gap_vaso` → `prd-utpbi-s3-gap-vaso` | `qs_s3_gap_vaso/cloudbuild.yaml` |
| STT | `qsmart_transcribe` → `prd-utpbi-qsmart-transcribe` | `qsmart_transcribe/cloudbuild.yaml` |
| Orquestación | Workflow `queuesmart-vaso-pipeline` | `queuesmart_vaso/workflows/vaso_pipeline.yaml` |

DDL/SPs BQ siguen en monorepo `monorep-utp-funcionts-runs/queuesmart_vaso/bigquery/` (si aún no están en BQ).

## Redeploy (Cloud Shell, raíz `speech_counter`)

```bash
cd ~/speech_counter   # o la ruta de tu clon

# 1) Jobs (activador Cloud Build o submit manual)
gcloud builds submit --config=qs_s3_gap_vaso/cloudbuild.yaml \
  --project=prd-utpbi-data-operation .

gcloud builds submit --config=qsmart_transcribe/cloudbuild.yaml \
  --project=prd-utpbi-data-operation .

# 2) Workflow STT (ya no Whisper)
gcloud workflows deploy queuesmart-vaso-pipeline \
  --source=queuesmart_vaso/workflows/vaso_pipeline.yaml \
  --location=us-central1 \
  --project=prd-utpbi-data-operation \
  --service-account=genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com

# 3) Prueba
gcloud workflows run queuesmart-vaso-pipeline \
  --location=us-central1 \
  --project=prd-utpbi-data-operation \
  --data='{"process_date":"2026-09-10"}'
```

El workflow inyecta env vaso al Job STT (`QS_ENRICHED_TABLE`, `QS_HIST_*`, `QS_MANIFEST_PREFIX=state/stt_manifests_vaso`) para no escribir en tablas prod.