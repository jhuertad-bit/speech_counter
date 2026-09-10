-- Catálogo Cita Mentor (GCS Firebase → GCS nuestro)
-- Proyecto: prd-utpbi-data-operation | Dataset: raw_cita_promotor (US)
--
-- Path típico:
--   audios/mentores/{DD-MM-YYYY}/{folder_id}/{file}.m4a
--
-- CREATE DATASET (una vez, si no existe):
--   bq mk --location=US --dataset prd-utpbi-data-operation:raw_cita_promotor

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.raw_cita_promotor.hist_cita_mentor_audio_catalog` (
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
  description = 'Catálogo Cita Mentor: audios/mentores/ desde Firebase; duration/codec vía ffprobe; dedup por gcs_uri'
);
