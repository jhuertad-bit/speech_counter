# cr_serialize_queuesmart — VASO Whisper en PRD

Cloud Run Job Whisper local sobre audios de **producción**, escribiendo en tablas
**vaso** (misma estructura que Chirp STT). No toca `hist_queuesmart_mp3_gen_ia_*`.

| | Chirp prod | Este Job (vaso) |
|---|---|---|
| Lee GCS | PRD bucket | PRD bucket |
| Lee enriched / catalog | prod | **`queuesmart_mp3_enriched_vaso`** / **`hist_queesmart_mp3_catalog_vaso`** |
| Escribe | `hist_*_gen_ia_*` | `hist_queuesmart_mp3_whisper_vaso_raw` / `_prd` |
| Job | — | `prd-utpbi-queuesmart-audio-serialize-whisper` |

Override de tablas de lectura (opcional): `QS_TABLE_ENRICHED`, `QS_TABLE_CATALOG`.

## Estructura

```
cr_serialize_queuesmart/
  cloudbuild.yaml
  scripts/cloudbuild_deploy.sh
  bigquery/tables/hist_queuesmart_mp3_whisper_vaso.sql
  src/   # Dockerfile + main + config (defaults PRD vaso)
```

## 1) Crear tablas vaso (una vez)

```bash
bq query --use_legacy_sql=false --location=US \
  --project_id=prd-utpbi-data-operation \
  < cr_serialize_queuesmart/bigquery/tables/hist_queuesmart_mp3_whisper_vaso.sql
```

## 2) Cloud Build

Activador: `cr_serialize_queuesmart/cloudbuild.yaml`

| Variable | Valor PRD vaso |
|---|---|
| `_PROJECT_ID` | `prd-utpbi-data-operation` |
| `_JOB_NAME` | `prd-utpbi-queuesmart-audio-serialize-whisper` |
| `_SERVICE_ACCOUNT` | `genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com` |
| `_BUCKET_NAME` | `prd-utp-stg-queuesmart` |
| `_TABLE_HIST_RAW` | `hist_queuesmart_mp3_whisper_vaso_raw` |
| `_TABLE_HIST_PRD` | `hist_queuesmart_mp3_whisper_vaso_prd` |

```bash
gcloud builds submit \
  --project=prd-utpbi-data-operation \
  --config=cr_serialize_queuesmart/cloudbuild.yaml \
  --substitutions=_PROJECT_ID=prd-utpbi-data-operation,_JOB_NAME=prd-utpbi-queuesmart-audio-serialize-whisper,_SERVICE_ACCOUNT=genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com,_BUCKET_NAME=prd-utp-stg-queuesmart \
  .
```

## 3) Ejecutar muestra de audios

```bash
# Un día (FLACs del día en queuesmart_mp3_enriched_vaso)
gcloud run jobs execute prd-utpbi-queuesmart-audio-serialize-whisper \
  --region=us-central1 --project=prd-utpbi-data-operation \
  --update-env-vars=FECHA_AUDIO=2026-09-10

# URIs puntuales (prueba vaso)
gcloud run jobs execute prd-utpbi-queuesmart-audio-serialize-whisper \
  --region=us-central1 --project=prd-utpbi-data-operation \
  --update-env-vars=GCS_URIS='gs://prd-utp-stg-queuesmart/data/input/queuesmart_mp3/imported_from_s3/2026-09-10/ARCHIVO.flac'
```

## Comparar Chirp vs Whisper

```sql
SELECT
  c.gcs_uri,
  c.transcripcion AS chirp,
  w.transcripcion AS whisper
FROM `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_prd` AS c
INNER JOIN `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_whisper_vaso_prd` AS w
  USING (gcs_uri)
WHERE c.process_date = DATE '2026-09-10';
```
