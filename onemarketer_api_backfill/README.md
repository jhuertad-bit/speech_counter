# onemarketer_api_backfill

Cloud Run **Job** one-shot: reprocesa `reporteAtenciones` desde **2026-06-29** con flatten/alias `lcra_*`.

Carpeta **aparte** de `onemarketer-api` para que el activador Cloud Build no redespliegue el servicio HTTP diario.

| Pieza | Path |
|-------|------|
| Servicio diario | `onemarketer-api/` → `cloudbuild.yaml` |
| Job backfill | `onemarketer_api_backfill/` → `cloudbuild.yaml` |

La imagen COPY `onemarketer-api/src` (fix lcra + ETL + load BQ).  
**Importante:** el activador Cloud Build solo ve `onemarketer_api_backfill/**`.  
Si cambias `onemarketer-api/src` (schema, flatten, load), hay que **tocar esta carpeta** (o build manual) para que el Job tome el código nuevo.

Fix 2026-11-12: load BQ usa schema de la tabla destino (evita 400 por `fecha_evento` ausente en JSON local).  
Fix 2026-11-12b: campos faltantes → JSON `null` (no `""`); `""` rompe DATE/INTEGER al load.  
Fix 2026-11-12c: coerce `"0"`→`0` etc. según schema antes del JSONL/load.  
Fix 2026-11-12e: Job cwd → `tablas/` (no `src/tablas/`); coerce con schema BQ real; log `errors[]`.  
Fix 2026-11-12f: `fecha_evento` REQUIRED en BQ → siempre `day` YYYY-MM-DD (nunca null).  
Fix 2026-11-12g: rellena **todos** los REQUIRED del schema BQ (`fecha_procesamiento` → now UTC, etc.).  
Fix 2026-11-12h: `reporteAtenciones.json` = schema PRD real (casi todo STRING; `fecha_procesamiento` DATETIME; col `"Time Wait Operator"`).

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
