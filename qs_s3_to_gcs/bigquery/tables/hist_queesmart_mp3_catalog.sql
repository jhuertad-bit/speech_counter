-- Catálogo de audios QueeSmart (S3 → GCS, convertidos a MP3 + loudnorm) — PRODUCCIÓN
-- Proyecto: prd-utpbi-data-operation | Dataset: raw_queue_smart (US)
--
-- Migración si la tabla ya existe:
--   ALTER TABLE `prd-utpbi-data-operation.raw_queue_smart.hist_queesmart_mp3_catalog`
--     ADD COLUMN IF NOT EXISTS source_file_name STRING,
--     ADD COLUMN IF NOT EXISTS convert_method STRING;

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.raw_queue_smart.hist_queesmart_mp3_catalog` (
  fecha_audio DATE NOT NULL,
  fecha_procesamiento TIMESTAMP NOT NULL,
  file_name STRING NOT NULL,
  source_file_name STRING,
  gcs_uri STRING NOT NULL,
  gcs_path STRING,
  campus_code STRING,
  type_code STRING,
  correlative STRING,
  s3_uri STRING,
  s3_key STRING,
  file_size_bytes INT64,
  sync_mode STRING,
  convert_method STRING
)
PARTITION BY fecha_audio
OPTIONS (
  description = 'Catálogo QueeSmart: audio S3 convertido a MP3 (loudnorm) en GCS; source_file_name = join con tickets_hist_raw.audio'
);
