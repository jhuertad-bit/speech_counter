-- Catálogo de audios QueeSmart (S3 → GCS, convertidos a MP3 + loudnorm) — PRODUCCIÓN
-- Proyecto: prd-utpbi-data-operation | Dataset: raw_queue_smart (US)
--
-- Migración si la tabla ya existe:
--   ALTER TABLE `….hist_queesmart_mp3_catalog`
--     ADD COLUMN IF NOT EXISTS gcs_original_uri STRING,
--     ADD COLUMN IF NOT EXISTS gcs_original_path STRING;
--   (ver bigquery/sqls/alter_gcs_original_path.sql)

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.raw_queue_smart.hist_queesmart_mp3_catalog` (
  fecha_audio DATE NOT NULL,
  fecha_procesamiento TIMESTAMP NOT NULL,
  file_name STRING NOT NULL,
  source_file_name STRING,
  gcs_uri STRING NOT NULL,
  gcs_path STRING,
  gcs_original_uri STRING,
  gcs_original_path STRING,
  campus_code STRING,
  type_code STRING,
  correlative STRING,
  s3_uri STRING,
  s3_key STRING,
  file_size_bytes INT64,
  duration_seconds FLOAT64,
  sync_mode STRING,
  convert_method STRING,
  actual_format STRING,
  encoding STRING
)
PARTITION BY fecha_audio
OPTIONS (
  description = 'Catálogo QueeSmart: FLAC STT en gcs_*; original S3 en gcs_original_*; source_file_name = basename join tickets'
);
