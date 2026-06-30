-- MP3 + CRM enriquecido (join audio file_name ↔ ticketero.audio). Input para Gen IA / analytics.

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET_RAW}.queuesmart_mp3_enriched` (
  process_day DATE NOT NULL,
  match_status STRING NOT NULL,
  gcs_uri STRING,
  file_name STRING,
  audio STRING,
  record_id STRING,
  campus_code STRING,
  type_code STRING,
  correlative STRING,
  file_size_bytes INT64,
  cliente_tipo STRING,
  cliente_estado STRING,
  cliente_url STRING,
  asesor_nombre STRING,
  asesor_usuario STRING,
  asesor_codigo STRING,
  num_celular STRING,
  enviado_sms STRING,
  transferido INT64,
  apellido_paterno STRING,
  audio_fecha DATE,
  catalog_fecha_procesamiento TIMESTAMP,
  crm_fecha_procesamiento TIMESTAMP,
  load_date DATETIME
)
PARTITION BY process_day
OPTIONS (
  description = 'QueeSmart MP3 + CRM Ticketero — cruce GCS ↔ SQL por nombre de audio'
);
