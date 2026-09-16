-- =============================================================================
-- Tablas VASO (shadow) — Whisper QueueSmart
-- Misma estructura que hist_queuesmart_mp3_gen_ia_process_data_raw / _prd
-- NO son las tablas productivas de Chirp STT.
--
-- Lectura de audios/tickets: sí usa enriched/catalog de PRD.
-- Escritura: solo estas tablas vaso.
--
--   bq query --use_legacy_sql=false --location=US \
--     --project_id=prd-utpbi-data-operation \
--     < cr_serialize_queuesmart/bigquery/tables/hist_queuesmart_mp3_whisper_vaso.sql
-- =============================================================================

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_whisper_vaso_raw` (
  process_date DATE,
  gcs_uri STRING,
  file_name STRING,
  source_file_name STRING,
  audio STRING,
  recordid STRING,
  rowid INT64,
  codagencia STRING,
  gcs_path STRING,
  campus_code STRING,
  type_code STRING,
  correlative STRING,
  file_size_bytes INT64,
  duration_seconds FLOAT64,
  sync_mode STRING,
  convert_method STRING,
  s3_uri STRING,
  match_status STRING,
  asesornombre STRING,
  asesorusuario STRING,
  asesorcodigo STRING,
  ndoc STRING,
  nombresusuario STRING,
  numcelular STRING,
  clientetipo STRING,
  `database` STRING,
  json_text STRING,
  full_response STRING,
  status STRING,
  transcripcion STRING,
  transcripcion_con_hablantes STRING,
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
  description = 'VASO Whisper QueueSmart — espejo de hist_*_gen_ia_process_data_raw (no prod Chirp)'
);

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_whisper_vaso_prd` (
  process_date DATE,
  gcs_uri STRING,
  file_name STRING,
  source_file_name STRING,
  audio STRING,
  recordid STRING,
  rowid INT64,
  codagencia STRING,
  campus_code STRING,
  type_code STRING,
  correlative STRING,
  file_size_bytes INT64,
  duration_seconds FLOAT64,
  match_status STRING,
  asesornombre STRING,
  asesorusuario STRING,
  asesorcodigo STRING,
  ndoc STRING,
  nombresusuario STRING,
  numcelular STRING,
  clientetipo STRING,
  `database` STRING,
  transcripcion STRING,
  transcripcion_con_hablantes STRING,
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
  description = 'VASO Whisper QueueSmart — espejo de hist_*_gen_ia_process_data_prd (no prod Chirp)'
);
