# cr_serialize_queuesmart — VASO Whisper (sin hablantes)

Cloud Run Job **faster-whisper** sobre audios de producción, escribiendo en tablas
**vaso**. No toca `hist_queuesmart_mp3_gen_ia_*`.

| Campo | Contenido |
|---|---|
| `transcripcion` | `[MM:SS] texto` (contrato Counter / Gemini) |
| `transcripcion_con_hablantes` | `NULL` (Whisper no diariza; comercial fuera de scope) |

| | Chirp prod | Este Job (vaso) |
|---|---|---|
| Lee GCS | PRD bucket | PRD bucket |
| Lee enriched / catalog | prod | **`queuesmart_mp3_enriched_vaso`** / **`hist_queesmart_mp3_catalog_vaso`** |
| Escribe | `hist_*_gen_ia_*` | `hist_queuesmart_mp3_whisper_vaso_raw` / `_prd` |
| Job | — | `prd-utpbi-queuesmart-audio-serialize-whisper` |

## Estructura

```
cr_serialize_queuesmart/
  cloudbuild.yaml
  scripts/cloudbuild_deploy.sh
  bigquery/tables/hist_queuesmart_mp3_whisper_vaso.sql
  src/   # Dockerfile + main.py + config
```

## Recursos

Default Cloud Build / Job: **GPU NVIDIA L4**, **16Gi / 8 CPU**, **parallelism=3**, **task-timeout=24h**.

| | GPU (default) | CPU |
|---|---|---|
| Dockerfile | `Dockerfile.gpu` | `Dockerfile` |
| Imagen | `queuesmart-audio-serialize-whisper-gpu` | `queuesmart-audio-serialize-whisper` |
| Device | `cuda` / `float16` | `cpu` / `int8` |
| Parallelism | `3` | `10` |

Whisper (defaults rápidos, override por env):
- `WHISPER_BEAM_SIZE=1`
- `WHISPER_WORD_TIMESTAMPS=false`
- `WHISPER_CONDITION_ON_PREVIOUS=false`
- `WHISPER_DEVICE=cuda|cpu`

Workflow: cuenta padres en `enriched_vaso` y lanza `taskCount`. Con GPU deja `whisper_max_tasks` ≤ cuota L4 (p. ej. 3).

Si ves `maximum timeout of 3600 seconds`:

```bash
gcloud run jobs update prd-utpbi-queuesmart-audio-serialize-whisper \
  --region=us-central1 --project=prd-utpbi-data-operation \
  --task-timeout=86400s --parallelism=3 --memory=16Gi --cpu=8 \
  --gpu=1 --gpu-type=nvidia-l4 --no-gpu-zonal-redundancy
```

Volver a CPU en el activador: `_USE_GPU=false,_DOCKERFILE=Dockerfile,_IMAGE_NAME=queuesmart-audio-serialize-whisper,_PARALLELISM=10,_MEMORY=32Gi`.

## Deploy (Cloud Build)

```bash
gcloud builds submit \
  --project=prd-utpbi-data-operation \
  --config=cr_serialize_queuesmart/cloudbuild.yaml \
  --substitutions=_PROJECT_ID=prd-utpbi-data-operation,_JOB_NAME=prd-utpbi-queuesmart-audio-serialize-whisper,_SERVICE_ACCOUNT=genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com,_BUCKET_NAME=prd-utp-stg-queuesmart \
  .
```

## Ejecutar

```bash
gcloud run jobs execute prd-utpbi-queuesmart-audio-serialize-whisper \
  --region=us-central1 --project=prd-utpbi-data-operation \
  --update-env-vars=FECHA_AUDIO=2026-08-01
```
