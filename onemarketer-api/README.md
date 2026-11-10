# onemarketer-api

Cloud Function **Gen2** (HTTP): `reportapi?type=cases|operator` → GCS → BQ `reporteAtenciones` / `reporteAccesoOperadores`.

Incluye fix `normalize_reporte_atenciones_lcra` (lead/dni desde ~2026-06-29).

## Deploy (Cloud Build)

Antes: shell local (`src/deploy_gen2_fixed.sh`).  
Ahora: activador → `cloudbuild.yaml` → `gcloud functions deploy --gen2` (**reemplaza** la función con el mismo `_FUNCTION_NAME`).

### Descubrir el nombre en PRD

```bash
gcloud functions list --project=prd-utpbi-data-operation --gen2 \
  --filter="name~onemarketer" --format="table(name,state,updateTime)"

gcloud run services list --project=prd-utpbi-data-operation --region=us-central1 \
  --filter="metadata.name~onemarketer" --format="table(metadata.name,status.url)"

gcloud scheduler jobs list --project=prd-utpbi-data-operation --location=us-central1 \
  --filter="name~onemarketer" --format="table(name,schedule,httpTarget.uri)"
```

Usa ese nombre exacto en `_FUNCTION_NAME` del activador.

### Sustituciones típicas

| Variable | Ejemplo |
|----------|---------|
| `_PROJECT_ID` | `prd-utpbi-data-operation` |
| `_FUNCTION_NAME` | el de `gcloud functions list` (ej. `prd-utpbi-onemarketer-api`) |
| `_SERVICE_ACCOUNT` | email completo SA |
| `_BUCKET_NAME` | bucket staging onemarketer |
| `_DATASET_ID` | `raw_onemarketer` |
| `_OAUTH_SECRET` | id Secret Manager OAuth |
| `_LOCATION` | `us-central1` |

Backfill histórico: carpeta aparte `../onemarketer_api_backfill/`.
