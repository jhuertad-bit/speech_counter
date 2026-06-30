-- Tabla histórica: capa curada para consumo (dashboards / CRM)
-- Reemplazar ${PROJECT_ID} y ${DATASET_ANALYTICS} al desplegar.

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET_ANALYTICS}.hist_onemarketer_whatsapp_gen_ia_process_data_prd` (
  process_date DATE,
  gcs_uri STRING,
  idcase INT64,
  idmessage INT64,
  waid STRING,
  duration_seconds FLOAT64,
  transcripcion STRING,
  resumen STRING,
  intencion STRING,
  idioma STRING,
  tono STRING,
  entidades STRING,
  observaciones STRING,
  chat_text STRING,
  chat_origin STRING,
  load_date DATETIME
)
PARTITION BY process_date
OPTIONS (
  description = 'Gen IA WhatsApp OneMarketer — capa prd / consumo'
);
