# cr_serialize_cita — Whisper LOCAL (Promotor + Mentores)

Misma imagen Docker; **dos Cloud Run Jobs** vía `CITA_CANAL`:

| Canal | Job | Catálogo | Destino Whisper |
|---|---|---|---|
| promotor | `prd-utpbi-cita-promotor-audio-serialize-whisper` | `hist_cita_promotor_audio_catalog` | `hist_cita_promotor_audio_whisper_*` |
| mentor | `prd-utpbi-cita-mentor-audio-serialize-whisper` | `hist_cita_mentor_audio_catalog` | `hist_cita_mentor_audio_whisper_*` |

Dataset: `raw_cita_promotor`. Salida: `transcripcion` con `[MM:SS]`.

## Estructura

```
cr_serialize_cita/
  cloudbuild.yaml
  deploy.sh
  README.md
  bigquery/tables/hist_cita_audio_whisper.sql
  scripts/cloudbuild_deploy.sh
  src/
    Dockerfile          # CPU
    Dockerfile.gpu      # NVIDIA L4 (default en cloudbuild)
    main.py
    requirements.txt
    config/config.json
```

Labels de costo: `project=cita`, `canal=promotor|mentor`, `accelerator=gpu|cpu`.

## 1) Tablas (una vez)

```bash
bq query --use_legacy_sql=false --location=US \
  --project_id=prd-utpbi-data-operation \
  < cr_serialize_cita/bigquery/tables/hist_cita_audio_whisper.sql
```

## 2) Cloud Build (desde la raíz del monorepo)

```bash
gcloud builds submit \
  --project=prd-utpbi-data-operation \
  --config=cr_serialize_cita/cloudbuild.yaml \
  --substitutions=_PROJECT_ID=prd-utpbi-data-operation,_SERVICE_ACCOUNT=genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com \
  .
```

Solo un canal:

```bash
# solo promotor
--substitutions=...,_DEPLOY_CANALES=promotor

# solo mentor
--substitutions=...,_DEPLOY_CANALES=mentor
```

## 3) Ejecutar un día

```bash
gcloud run jobs execute prd-utpbi-cita-promotor-audio-serialize-whisper \
  --region=us-central1 --project=prd-utpbi-data-operation \
  --update-env-vars=FECHA_AUDIO=2026-09-16

gcloud run jobs execute prd-utpbi-cita-mentor-audio-serialize-whisper \
  --region=us-central1 --project=prd-utpbi-data-operation \
  --update-env-vars=FECHA_AUDIO=2026-09-16
```

Los workflows `promotores_gcs_copy` / `mentores_gcs_copy` llaman estos Jobs tras el copy (`run_whisper`, default `true`).

## GPU (default) vs CPU

Por defecto el activador despliega **NVIDIA L4**:

| | GPU | CPU |
|---|---|---|
| Dockerfile | `Dockerfile.gpu` | `Dockerfile` |
| Imagen | `cita-audio-serialize-whisper-gpu` | `cita-audio-serialize-whisper` |
| Device | `cuda` / `float16` | `cpu` / `int8` |
| Flags Job | `--gpu=1 --gpu-type=nvidia-l4 --no-gpu-zonal-redundancy` | sin GPU |
| Parallelism | `3` (1 GPU/task; sube según cuota) | `10` |

Activador (GPU, default del yaml):

```text
_PROJECT_ID=prd-utpbi-data-operation
_SERVICE_ACCOUNT=genesys-audio-processor@prd-utpbi-data-operation.iam.gserviceaccount.com
```

Volver a CPU:

```text
_USE_GPU=false
_DOCKERFILE=Dockerfile
_IMAGE_NAME=cita-audio-serialize-whisper
_PARALLELISM=10
_MEMORY=32Gi
```

Prerequisito GPU: cuota L4 en `us-central1` y API Cloud Run con GPUs habilitadas.
