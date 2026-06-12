-- Tabla histórica: respuesta cruda + JSON parseado (capa RAW)
-- Reemplazar ${PROJECT_ID} y ${DATASET_ANALYTICS} al desplegar.

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET_ANALYTICS}.hist_onemarketer_whatsapp_gen_ia_process_data_raw` (
  process_date DATE,
  gcs_uri STRING,
  idcase INT64,
  idmessage INT64,
  waid STRING,
  duration_seconds FLOAT64,
  chat_text STRING,
  chat_origin STRING,
  chat_user STRING,
  json_text STRING,
  full_response STRING,
  status STRING,
  transcripcion STRING,
  resumen STRING,
  intencion STRING,
  idioma STRING,
  tono STRING,
  entidades STRING,
  observaciones STRING,
  load_date DATETIME
)
PARTITION BY process_date
OPTIONS (
  description = 'Gen IA sobre audios MP3 WhatsApp/OneMarketer — capa raw (JSON + campos extraídos)'
);
