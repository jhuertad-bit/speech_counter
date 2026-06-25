# QueeSmart BigQuery — consolidación MP3 (patrón Genesys)

Pipeline analítico sobre audios QueeSmart, alineado al patrón **vaso de agua** de Genesys y al flujo Gen IA de OneMarketer.

## Arquitectura

```
hist_queesmart_mp3_catalog       (RAW — job qs_s3_to_gcs)
        │
        ▼  sp_queuesmart_mp3_gen_ia(v_fecha)  [adf_speech_analytics / US]
        ▼
hist_queuesmart_mp3_gen_ia_*     (transcripción, resumen, intención…)

(Opcional — CRM Ticketero, flujo aparte:)
hist_queuesmart_ticketero_raw → sp_queuesmart_mp3_consolidate → queuesmart_mp3_enriched
```

## Comparación con Genesys / OneMarketer

| Genesys | QueeSmart |
|---------|-----------|
| `conversations_raw` → `conversations` | `hist_queesmart_mp3_catalog` → `queuesmart_mp3_catalog` |
| `evaluations_raw` → `evaluations` | `hist_queuesmart_ticketero_raw` → `queuesmart_ticketero_crm` |
| — | `queuesmart_mp3_enriched` (cruce GCS + CRM) |
| SP Gen IA | `sp_onemarketer_whatsapp_gen_ia` | `sp_queuesmart_mp3_gen_ia` |

## Despliegue PRD — Gen IA

Todos los SQL de Gen IA vienen con IDs fijos `prd-utpbi-data-operation`:

```bash
# Vista (us-central1)
bq query --use_legacy_sql=false --location=us-central1 \
  < queuesmart/bigquery/views/v_hist_queesmart_mp3_catalog_ia_input.sql

# Tablas + SP (US)
bq query --use_legacy_sql=false --location=US \
  < queuesmart/bigquery/tables/hist_queuesmart_mp3_gen_ia_raw.sql
bq query --use_legacy_sql=false --location=US \
  < queuesmart/bigquery/tables/hist_queuesmart_mp3_gen_ia_prd.sql
bq query --use_legacy_sql=false --location=US \
  < queuesmart/bigquery/procedures/sp_queuesmart_mp3_gen_ia.sql
```

## Ejecutar Gen IA

```sql
CALL `prd-utpbi-data-operation.adf_speech_analytics.sp_queuesmart_mp3_gen_ia`(
  DATE_SUB(CURRENT_DATE('America/Lima'), INTERVAL 1 DAY)
);
```

Ver `examples/call_sp_gen_ia_prd.sql` y `deploy/prd_gen_ia.sql`.

## Orquestación diaria sugerida (PRD — Gen IA)

1. Cloud Run `qs_s3_to_gcs` (ayer) → `hist_queesmart_mp3_catalog`
2. `CALL adf_speech_analytics.sp_queuesmart_mp3_gen_ia(ayer)` — **US**

Ver `examples/call_sp_gen_ia_prd.sql` y vista `v_hist_queesmart_mp3_catalog_ia_input`.

### Gen IA — prerequisitos

- Dataset `adf_speech_analytics` en **US** (no us-central1)
- Modelo `gemini-2-5-flash` en ese dataset
- Conexión `utp_gen_ia_process` con acceso al bucket GCS QueeSmart
- Tablas: `hist_queuesmart_mp3_gen_ia_process_data_raw` / `_prd`

Desplegar tablas + SP con `--location=US`.

## match_status en enriched

| Valor | Significado |
|-------|-------------|
| `BOTH` | Audio en GCS y fila CRM |
| `GCS_ONLY` | MP3 en GCS sin CRM |
| `CRM_ONLY` | CRM sin archivo en GCS (aún no sincronizado) |
