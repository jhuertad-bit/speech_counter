# Incidencia: lead vacío en `reporteAtenciones` desde 2026-06-29

## Resumen

Los campos `lcra_*` (listaCasosReporteAtenciones) llegan vacíos a  
`prd-utpbi-data-operation.raw_onemarketer.reporteAtenciones`.

Carga: Cloud Run **`onemarketer-api`** → `POST reportapi?type=cases`.  
Antes del filtro de schema no había flatten/alias: si la API anida o renombra, `filter_and_normalize_message` deja `""`.

Conversaciones / templates = otro pipeline (`onemarketer` + `getChats.php` → `reporte_chats.template`).

## Corte confirmado (BQ job)

Serie `DATE(start_time)` 2026-06-20 … 2026-07-15:

| Rango | lead_vacio / n | dni_vacio / n |
|-------|----------------|---------------|
| 20–28 jun | parcial (~70–90%) | parcial |
| **29 jun →** | **100%** | **100%** |

Ejemplo: 2026-06-28 → 1990/2421 lead vacío; **2026-06-29 → 3938/3938**.

Firma típica de rename/nest en payload (no de volumen ni de partición BQ).

## Diagnóstico BQ

```bash
bq query --project_id=prd-utpbi-data-operation --location=US --use_legacy_sql=false \
  < onemarketer-api/bigquery/sqls/diagnose_reporteAtenciones_lead_vacios.sql
```

**Importante:** el JSONL de landing GCS ya sale *filtrado* (solo columnas schema).  
Para ver keys reales hay que pegarle a la API sin filtro:

```bash
cd speech_counter/onemarketer-api/src
# con secretos ONEMARKETER_* / SA Cloud Run
python probe_reportapi_keys.py --day 2026-06-28 --sample 1
python probe_reportapi_keys.py --day 2026-06-29 --sample 1
```

## Fix (código)

1. `normalize_reporte_atenciones_lcra()` en `main.py`: flatten nested `listaCasos*` + alias → `lcra_*` **antes** del filter.
2. Validar con `probe_reportapi_keys.py` que `lcra_lead` / `lcra_dni` salen poblados.
3. Redeploy `onemarketer-api` (Cloud Build `speech_counter/onemarketer-api`).
4. Si templates/chats: revisar `onemarketer` + `getChats` (parser ya tolera `Undefined index: template`).

## Reproceso histórico

**No usar** el servicio HTTP con `days_back` grande (timeout 540s).

Job en carpeta **aparte** (activador Cloud Build distinto):  
`speech_counter/onemarketer_api_backfill/` — ver su `README.md`.

```bash
# Deploy: activador → onemarketer_api_backfill/cloudbuild.yaml
gcloud run jobs execute prd-utpbi-onemarketer-api-backfill \
  --region=us-central1 --project=prd-utpbi-data-operation --tasks=1 \
  --update-env-vars=BACKFILL_START_DATE=2026-06-29,BACKFILL_TABLES=reporteAtenciones
```

Por cada día borra partición `$YYYYMMDD` y vuelve a cargar.

Validar de nuevo el SQL de diagnóstico + match en `v_onemarketer_caso_crm_lead`.
