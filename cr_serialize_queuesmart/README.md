# cr_serialize_queuesmart — VASO Whisper + diarización pyannote

Cloud Run Job **faster-whisper** + **pyannote/speaker-diarization-3.1** sobre audios
de producción, escribiendo en tablas **vaso**. No toca `hist_queuesmart_mp3_gen_ia_*`.

| Campo | Contenido |
|---|---|
| `transcripcion` | `[MM:SS] texto` (contrato Counter / Gemini) |
| `transcripcion_con_hablantes` | `[HH:MM:SS] Voz N: texto` (alineación por solapamiento) |

| | Chirp prod | Este Job (vaso) |
|---|---|---|
| Lee GCS | PRD bucket | PRD bucket |
| Lee enriched / catalog | prod | **`queuesmart_mp3_enriched_vaso`** / **`hist_queesmart_mp3_catalog_vaso`** |
| Escribe | `hist_*_gen_ia_*` | `hist_queuesmart_mp3_whisper_vaso_raw` / `_prd` |
| Job | — | `prd-utpbi-queuesmart-audio-serialize-whisper` |

## Requisitos diarización

1. Aceptar términos en Hugging Face:
   - https://huggingface.co/pyannote/speaker-diarization-3.1
   - https://huggingface.co/pyannote/segmentation-3.0
2. Crear secret en Secret Manager (ej. `HF_TOKEN`) con un token de lectura.
3. IAM `roles/secretmanager.secretAccessor` a la SA del Job.
4. En Cloud Build / deploy: `_HF_SECRET_NAME=HF_TOKEN` (o `HF_SECRET_NAME` en `deploy.sh`).

Sin token, el Job sigue transcribiendo Whisper y deja `transcripcion_con_hablantes` vacío.

## Estructura

```
cr_serialize_queuesmart/
  cloudbuild.yaml
  scripts/cloudbuild_deploy.sh
  bigquery/tables/hist_queuesmart_mp3_whisper_vaso.sql
  src/   # Dockerfile + main.py + diarize.py + config
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
| `_MEMORY` / `_CPU` | `32Gi` / `8` (Whisper + pyannote) |
| `_ENABLE_DIARIZATION` | `true` |
| `_HF_SECRET_NAME` | `HF_TOKEN` |

```bash
gcloud builds submit \
  --project=prd-utpbi-data-operation \
  --config=cr_serialize_queuesmart/cloudbuild.yaml \
  --substitutions=_PROJECT_ID=prd-utpbi-data-operation,_JOB_NAME=prd-utpbi-queuesmart-audio-serialize-whisper,_SERVICE_ACCOUNT=genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com,_BUCKET_NAME=prd-utp-stg-queuesmart,_HF_SECRET_NAME=HF_TOKEN \
  .
```

## 3) Ejecutar muestra

```bash
gcloud run jobs execute prd-utpbi-queuesmart-audio-serialize-whisper \
  --region=us-central1 --project=prd-utpbi-data-operation \
  --update-env-vars=FECHA_AUDIO=2026-09-10
```

## Comparar Chirp vs Whisper (+ hablantes)

```sql
SELECT
  c.gcs_uri,
  c.transcripcion AS chirp,
  w.transcripcion AS whisper_mmss,
  w.transcripcion_con_hablantes AS whisper_voz
FROM `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_prd` AS c
INNER JOIN `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_whisper_vaso_prd` AS w
  USING (gcs_uri)
WHERE c.process_date = DATE '2026-09-10';
```
