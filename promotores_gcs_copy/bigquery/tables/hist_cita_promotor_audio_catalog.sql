-- Catálogo Cita Promotor (GCS Firebase → GCS nuestro)
-- Proyecto: prd-utpbi-data-operation | Dataset: raw_cita_promotor (US)
--
-- Path típico:
--   audios/{DD-MM-YYYY}/{folder_uuid}/{file_uuid}.m4a
--
-- CREATE DATASET (una vez, si no existe):
--   bq mk --location=US --dataset prd-utpbi-data-operation:raw_cita_promotor

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.raw_cita_promotor.hist_cita_promotor_audio_catalog` (
  fecha_audio DATE NOT NULL,
  fecha_procesamiento TIMESTAMP NOT NULL,
  file_name STRING NOT NULL,
  gcs_uri STRING NOT NULL,
  gcs_path STRING,
  source_gcs_uri STRING,
  source_gcs_path STRING,
  folder_uuid STRING,
  file_size_bytes INT64,
  content_type STRING,
  duration_seconds FLOAT64,
  audio_codec STRING,
  sample_rate_hz INT64,
  channels INT64,
  format_name STRING,
  bit_rate INT64,
  sync_mode STRING,
  copy_result STRING
)
PARTITION BY fecha_audio
OPTIONS (
  description = 'Catálogo Cita Promotor: audios copiados de Firebase; duration/codec vía ffprobe; dedup por gcs_uri'
);

-- Si la tabla ya existía sin columnas de probe:
-- ALTER TABLE `prd-utpbi-data-operation.raw_cita_promotor.hist_cita_promotor_audio_catalog`
--   ADD COLUMN IF NOT EXISTS duration_seconds FLOAT64,
--   ADD COLUMN IF NOT EXISTS audio_codec STRING,
--   ADD COLUMN IF NOT EXISTS sample_rate_hz INT64,
--   ADD COLUMN IF NOT EXISTS channels INT64,
--   ADD COLUMN IF NOT EXISTS format_name STRING,
--   ADD COLUMN IF NOT EXISTS bit_rate INT64;
