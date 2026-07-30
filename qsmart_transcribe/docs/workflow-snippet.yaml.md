# Encaje en Cloud Workflows

Ya está cableado en `queuesmart/workflows/daily_pipeline.yaml`:

1. Job S3→GCS prepare/worker  
2. `sp_queuesmart_mp3_consolidate`  
3. Job `prd-utpbi-qsmart-transcribe` prepare/worker (**reemplaza** `sp_queuesmart_mp3_gen_ia`)  
4. `sp_queuesmart_audio_analisis_ia`

Args opcionales del workflow:

| Arg | Default |
|-----|---------|
| `stt_job_name` | `prd-utpbi-qsmart-transcribe` |
| `stt_manifest_prefix` | `state/stt_manifests` |

**Importante:** el Job Cloud Run debe existir antes de redeployar el workflow; si no, fallará en `run_stt_prepare`.
