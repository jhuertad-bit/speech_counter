# mentores_gcs_copy

Clon de `promotores_gcs_copy` para audios de **mentores**.

Mismo bucket Firebase, mismo dataset BQ `raw_cita_promotor`, **otra carpeta origen**, **otra tabla** y manifiestos separados para no chocar con promotores.

## Rutas

```
Origen   gs://citapromotor-utp.firebasestorage.app/audios/mentores/{DD-MM-YYYY}/{id}/*.m4a
                    │
            prepare (lista) → manifiesto en destino
                    │
            worker  (1 task = 1 objeto, stream copy + ffprobe + catálogo BQ)
                    ▼
Destino  gs://prd-utp-stg-citapromotor-9bd1430535b8/audios/mentores/{DD-MM-YYYY}/{id}/*.m4a
```

`SYNC_PROCESS_DATE` = `YYYY-MM-DD` (ayer Lima).  
Carpeta GCS = `%d-%m-%Y` → ej. `audios/mentores/07-09-2026/`.

| Recurso | Valor |
|---------|--------|
| Job | `prd-utpbi-mentores-gcs-copy` |
| Workflow | `prd-utpbi-mentores-gcs-copy` |
| Scheduler | `prd-sch-mentores-gcs-copy` · `0 5 * * *` Lima |
| Dataset | `raw_cita_promotor` (mismo que promotores) |
| Tabla catálogo | `hist_cita_mentor_audio_catalog` |
| Manifiesto | `state/manifests/mentores/{fecha}.jsonl` |
| Secret origen | `PromotoresSourceSa` (mismo Firebase) |
| SP Gen IA | **no** (solo copy + catálogo por ahora) |

## Flujo workflow

1. prepare (1 task)  
2. lee count del meta  
3. worker N tasks → copia GCS + insert catálogo BQ  

Args: `process_date` (default ayer Lima).

## Deploy

```bash
# DDL tabla
bq query --use_legacy_sql=false --location=US \
  --project_id=prd-utpbi-data-operation \
  < mentores_gcs_copy/bigquery/tables/hist_cita_mentor_audio_catalog.sql

# Cloud Run Job (vía Cloud Build o scripts/cloudbuild_deploy.sh)
# Sustituciones mínimas: _PROJECT_ID, _JOB_NAME=prd-utpbi-mentores-gcs-copy,
#   _SERVICE_ACCOUNT, _DEST_BUCKET_NAME=prd-utp-stg-citapromotor-9bd1430535b8,
#   _SOURCE_PROJECT_ID=citapromotor-utp,
#   _SOURCE_BUCKET_NAME=citapromotor-utp.firebasestorage.app,
#   _SOURCE_PREFIX=audios/mentores, _DEST_PREFIX=audios/mentores/

gcloud workflows deploy prd-utpbi-mentores-gcs-copy \
  --project=prd-utpbi-data-operation \
  --location=us-central1 \
  --source=mentores_gcs_copy/workflows/daily_pipeline.yaml \
  --service-account=genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com
```

## Diferencias vs promotores

| | Promotores | Mentores |
|--|------------|----------|
| Prefijo origen | `audios/` | `audios/mentores/` |
| Prefijo destino | `audios/` | `audios/mentores/` |
| Tabla | `hist_cita_promotor_audio_catalog` | `hist_cita_mentor_audio_catalog` |
| Manifiesto | `state/manifests/` | `state/manifests/mentores/` |
| SP | `sp_utpbi_gen_ia_cita_promotor` | *(pendiente; workflow solo copy+catálogo)* |
| Schedule | 04:00 Lima | 05:00 Lima |

## Credenciales

Misma SA JSON del secret `PromotoresSourceSa` (mismo proyecto/bucket Firebase). Ver `docs/credenciales-origen.txt`.
