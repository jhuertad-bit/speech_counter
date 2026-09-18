-- =============================================================================
-- Whisper Cita Promotor / Mentores
-- Dataset: raw_cita_promotor (US)
--
--   bq query --use_legacy_sql=false --location=US \
--     --project_id=prd-utpbi-data-operation \
--     < cr_serialize_cita/bigquery/tables/hist_cita_audio_whisper.sql
-- =============================================================================

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.raw_cita_promotor.hist_cita_promotor_audio_whisper_raw` (
  fecha_audio DATE,
  gcs_uri STRING,
  file_name STRING,
  folder_uuid STRING,
  gcs_path STRING,
  file_size_bytes INT64,
  duration_seconds FLOAT64,
  status STRING,
  transcripcion STRING,
  idioma STRING,
  canal STRING,
  json_text STRING,
  observaciones STRING,
  load_date DATETIME
)
PARTITION BY fecha_audio
OPTIONS (description = 'Whisper LOCAL Cita Promotor — 1 fila por gcs_uri');

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.raw_cita_promotor.hist_cita_promotor_audio_whisper_prd` (
  fecha_audio DATE,
  gcs_uri STRING,
  file_name STRING,
  folder_uuid STRING,
  gcs_path STRING,
  file_size_bytes INT64,
  duration_seconds FLOAT64,
  status STRING,
  transcripcion STRING,
  idioma STRING,
  canal STRING,
  observaciones STRING,
  load_date DATETIME
)
PARTITION BY fecha_audio
OPTIONS (description = 'Whisper LOCAL Cita Promotor — 1 fila por folder_uuid (merge)');

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.raw_cita_promotor.hist_cita_mentor_audio_whisper_raw` (
  fecha_audio DATE,
  gcs_uri STRING,
  file_name STRING,
  folder_uuid STRING,
  gcs_path STRING,
  file_size_bytes INT64,
  duration_seconds FLOAT64,
  status STRING,
  transcripcion STRING,
  idioma STRING,
  canal STRING,
  json_text STRING,
  observaciones STRING,
  load_date DATETIME
)
PARTITION BY fecha_audio
OPTIONS (description = 'Whisper LOCAL Cita Mentor — 1 fila por gcs_uri');

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.raw_cita_promotor.hist_cita_mentor_audio_whisper_prd` (
  fecha_audio DATE,
  gcs_uri STRING,
  file_name STRING,
  folder_uuid STRING,
  gcs_path STRING,
  file_size_bytes INT64,
  duration_seconds FLOAT64,
  status STRING,
  transcripcion STRING,
  idioma STRING,
  canal STRING,
  observaciones STRING,
  load_date DATETIME
)
PARTITION BY fecha_audio
OPTIONS (description = 'Whisper LOCAL Cita Mentor — 1 fila por folder_uuid (merge)');
