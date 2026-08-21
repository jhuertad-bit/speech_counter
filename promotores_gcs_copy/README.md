# promotores_gcs_copy

Cloud Run Job **GCS → GCS entre proyectos**, mismo patrón prepare/worker que `qs_s3_to_gcs`.

No usa S3, ffmpeg ni BigQuery. Origen: SA JSON (Secret Manager). Destino: SA del Job.

## Flujo

```
Origen   gs://citapromotor-utp.firebasestorage.app/audios/{DD-MM-YYYY}/{uuid}/{uuid}.m4a
                    │
            prepare (lista) → manifiesto en destino
                    │
            worker  (1 task = 1 objeto, stream copy)
                    ▼
Destino  gs://prd-utp-stg-citapromotor-9bd1430535b8/audios/{DD-MM-YYYY}/{uuid}/{uuid}.m4a
```

`SYNC_PROCESS_DATE` interno = `YYYY-MM-DD` (ayer Lima).
Carpeta en GCS = `gcs_date_folder_format` `%d-%m-%Y` → ej. 22-ago 04:00 Lima → procesa `2026-08-21` → lista `audios/21-08-2026/`.

Roles:

| `JOB_ROLE` | Qué hace |
|------------|----------|
| `prepare` | Lista el origen del día → `gs://destino/state/manifests/{fecha}.jsonl` |
| `worker` | `CLOUD_RUN_TASK_INDEX` copia 1 línea |

Orquesta el workflow `workflows/daily_pipeline.yaml` (prepare → lee count → worker N tasks).

## Config

`src/config/config.json` (placeholders) o env en el Job:

| Env | Qué es |
|-----|--------|
| `SOURCE_PROJECT_ID` | Proyecto del bucket origen |
| `SOURCE_BUCKET_NAME` | Bucket origen |
| `SOURCE_PREFIX` | Prefijo opcional en origen |
| `DEST_PROJECT_ID` / `GCP_PROJECT_ID` | Proyecto del Job y destino |
| `DEST_BUCKET_NAME` / `GCP_BUCKET_NAME` | Bucket destino (manifiesto + copias) |
| `DEST_PREFIX` | Prefijo destino (default `audios/`) |
| `SYNC_PROCESS_DATE` | `YYYY-MM-DD` (si no, ayer Lima) |
| `SYNC_MODE` | `daily_yesterday` o `backfill_all` |
| `SYNC_LAYOUT` | `date_folder` (default) o `flat` |

`date_folder`: lista `gs://origen/{prefix}/{carpeta-fecha}/`.  
Cita Promotor usa `dd-mm-yyyy` → `"gcs_date_folder_format": "%d-%m-%Y"`.

## Credenciales del origen (JSON)

No subas el JSON al repo ni lo pongas en `GOOGLE_APPLICATION_CREDENTIALS` del Job (eso también firmaría el destino).

Súbelo a Secret Manager en **nuestro** proyecto y el Job lo usa solo para leer origen:

```bash
gcloud secrets create PromotoresSourceSa \
  --project=prd-utpbi-data-operation \
  --replication-policy=automatic \
  --data-file=EL_JSON_QUE_TE_DIERON.json

gcloud secrets add-iam-policy-binding PromotoresSourceSa \
  --project=prd-utpbi-data-operation \
  --member="serviceAccount:genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

Con JSON, la copia es stream (lee con esa SA, escribe con la SA del Job). `rewrite` solo aplica si el origen se accede con ADC (IAM cross-project).

## IAM

- **Destino:** SA del Job = `roles/storage.objectAdmin`
- **Secret:** SA del Job = `roles/secretmanager.secretAccessor` sobre `PromotoresSourceSa`
- **Origen:** ya viene en el JSON; no hace falta IAM extra en el otro proyecto
- **BigQuery:** SA del Job = `roles/bigquery.dataEditor` en `raw_cita_promotor` + `roles/bigquery.jobUser` en el proyecto

## Catálogo BigQuery

Tras cada copia (o skip si ya estaba en GCS), el worker hace **ffprobe** (solo metadata)
e inserta una fila en:

`prd-utpbi-data-operation.raw_cita_promotor.hist_cita_promotor_audio_catalog`

Campos de audio: `duration_seconds`, `audio_codec`, `sample_rate_hz`, `channels`, `format_name`, `bit_rate`.
Dedup por `gcs_uri`. DDL: `bigquery/tables/hist_cita_promotor_audio_catalog.sql`

```bash
bq mk --location=US --dataset prd-utpbi-data-operation:raw_cita_promotor
bq query --use_legacy_sql=false --location=US --project_id=prd-utpbi-data-operation \
  < promotores_gcs_copy/bigquery/tables/hist_cita_promotor_audio_catalog.sql
```

(El Job también puede crear dataset/tabla en runtime vía `ensure_table` si tiene permisos.)

## Deploy (Cloud Build)

Sustituciones: `_PROJECT_ID`, `_JOB_NAME`, `_SERVICE_ACCOUNT`, `_DEST_BUCKET_NAME`, `_SOURCE_PROJECT_ID`, `_SOURCE_BUCKET_NAME`. Opcionales: `_SOURCE_PREFIX`, `_DEST_PREFIX`.

## Manual

```bash
# prepare
gcloud run jobs execute prd-utpbi-promotores-gcs-copy \
  --region=us-central1 --project=prd-utpbi-data-operation \
  --tasks=1 \
  --update-env-vars=JOB_ROLE=prepare,SYNC_PROCESS_DATE=2026-08-19

# worker (N = count del .meta.json)
gcloud run jobs execute prd-utpbi-promotores-gcs-copy \
  --region=us-central1 --project=prd-utpbi-data-operation \
  --tasks=N \
  --update-env-vars=JOB_ROLE=worker,SYNC_PROCESS_DATE=2026-08-19
```

Si el objeto ya está en destino, la task hace skip (`already_in_gcs`).
