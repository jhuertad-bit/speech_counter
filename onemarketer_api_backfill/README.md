# onemarketer_api_backfill

Cloud Run **Job** one-shot: reprocesa `reporteAtenciones` desde **2026-06-29** con flatten/alias `lcra_*`.

Carpeta **aparte** de `onemarketer-api` para que el activador Cloud Build no redespliegue el servicio HTTP diario.

| Pieza | Path |
|-------|------|
| Servicio diario | `onemarketer-api/` → `cloudbuild.yaml` |
| Job backfill | `onemarketer_api_backfill/` → `cloudbuild.yaml` |

La imagen COPY `onemarketer-api/src` (fix lcra + ETL). Tras cambiar el fix en `onemarketer-api`, hay que **volver a buildear este Job** (manual o commit touch aquí).

## Activador

Include: `onemarketer_api_backfill/**`  
Config: `onemarketer_api_backfill/cloudbuild.yaml`

Sustituciones: ver cabecera de `cloudbuild.yaml`.

## Ejecutar

```bash
gcloud run jobs execute prd-utpbi-onemarketer-api-backfill \
  --region=us-central1 --project=prd-utpbi-data-operation --tasks=1

# Prueba corta
gcloud run jobs execute prd-utpbi-onemarketer-api-backfill \
  --region=us-central1 --project=prd-utpbi-data-operation --tasks=1 \
  --update-env-vars=BACKFILL_START_DATE=2026-06-29,BACKFILL_END_DATE=2026-07-15
```

## Validar

```bash
bq query --project_id=prd-utpbi-data-operation --location=US --use_legacy_sql=false \
  < onemarketer-api/bigquery/sqls/diagnose_reporteAtenciones_lead_vacios.sql
```
