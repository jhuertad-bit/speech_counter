-- Tabla CRM Ticketero / QueeSmart → raw_queuesmart
-- Reemplazar ${PROJECT_ID} y ${DATASET_RAW} al desplegar.

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET_RAW}.hist_queuesmart_ticketero_raw` (
  fecha_extraccion DATE NOT NULL,
  fecha_procesamiento TIMESTAMP NOT NULL,
  apellido_paterno STRING,
  cliente_tipo STRING,
  cliente_estado STRING,
  cliente_url STRING,
  asesor_nombre STRING,
  asesor_usuario STRING,
  asesor_codigo STRING,
  transferido INT64,
  num_celular STRING,
  enviado_sms STRING,
  record_id STRING,
  audio STRING,
  audio_fecha DATE
)
PARTITION BY fecha_extraccion
OPTIONS (
  description = 'CRM Ticketero (SQL Server) — leads/oportunidades con audio QueeSmart'
);
