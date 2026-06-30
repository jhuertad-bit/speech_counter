# qs_sql_to_bq

ETL **SQL Server (on-prem)** → **BigQuery** `raw_queuesmart`.

Tabla destino: `hist_queuesmart_ticketero_raw` — CRM Ticketero con columna `Audio` (MP3 QueeSmart).

## Flujo

```
SQL Server (dbo.TablaPendiente)
        │  SELECT columnas CRM
        ▼
Cloud Run Job (extract.py)
        │  filtra por fecha en Audio (daily_yesterday / backfill)
        ▼
BigQuery raw_queuesmart.hist_queuesmart_ticketero_raw
```

## Columnas origen (según estructura conocida)

| SQL | BigQuery |
|-----|----------|
| doPaterno | apellido_paterno |
| ClienteTipo | cliente_tipo |
| ClienteEstado | cliente_estado |
| ClienteURL | cliente_url |
| AsesorNombre | asesor_nombre |
| AsesorUsuario | asesor_usuario |
| AsesorCodigo | asesor_codigo |
| Transferido | transferido |
| NumCelular | num_celular |
| EnviadoSMS | enviado_sms |
| RecordID | record_id |
| Audio | audio (+ `audio_fecha` parseada) |

Ajustar `column_map` en `config.json` si los nombres reales difieren.

## Pendiente (sin conexión aún)

Host, database y tabla van **vacíos** en config — se definen por **variables de entorno** en el activador.

Ver: [docs/sql-connection-pending.md](../docs/sql-connection-pending.md)

## Activador Cloud Build — variables

**Obligatorias:**

```
_PROJECT_ID=dev-utpbi-data-operation
_JOB_NAME=dev-utpbi-sql-to-bq-queuesmart
_SERVICE_ACCOUNT=dev-utp-eduflow-sa@dev-utpbi-data-operation.iam.gserviceaccount.com
_DATASET_ID=raw_queuesmart
_SQL_SERVER_HOST=...
_SQL_SERVER_DATABASE=...
_SQL_SOURCE_TABLE=...
_SQL_SERVER_USER=...
_SQL_SERVER_PASSWORD=...
```

**Opcionales:** `_SQL_SERVER_PORT`, `_SQL_SERVER_SCHEMA`, `_SQL_CUSTOM_QUERY`, `_SYNC_MODE`

## Modos sync

| Modo | Comportamiento |
|------|----------------|
| `daily_yesterday` | Solo filas cuya fecha en `Audio` = ayer (Lima) |
| `daily_last_n_days` | Últimos N días hasta ayer |
| `backfill_all` | Todas las filas del SELECT |

## Estructura

```
qs_sql_to_bq/
├── cloudbuild.yaml
├── scripts/cloudbuild_deploy.sh
├── bigquery/tables/hist_queuesmart_ticketero_raw.sql
├── docs/sql-connection-pending.md
└── src/
    ├── config/config.json
    ├── tablas/hist_queuesmart_ticketero_raw.json
    ├── sql_client.py
    ├── bq_loader.py
    ├── audio_filter.py
    ├── extract.py
    └── main.py
```

## IAM

SA del Job: `roles/bigquery.dataEditor` en `raw_queuesmart`.

## Prueba local (cuando tengan SQL)

```bash
cd qs_sql_to_bq/src
cp ../.env.example ../.env   # completar valores
export $(grep -v '^#' ../.env | xargs)
pip install -r requirements.txt
python main.py
```

## Relación con qs_s3_to_bq

- **qs_s3_to_gcs**: copia MP3 S3 → GCS + catálogo `hist_queesmart_mp3_catalog`
- **qs_sql_to_bq**: metadata CRM desde SQL → `hist_queuesmart_ticketero_raw`

Join futuro sugerido: `audio` (SQL) ↔ `file_name` / `gcs_uri` (catálogo MP3).
