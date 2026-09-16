-- =============================================================================
-- Catálogo VASO — gaps S3→GCS (prefijos Ticketero ≠ 6 chars / .audio)
-- Misma estructura que hist_queesmart_mp3_catalog.
-- NO escribe en el catálogo productivo.
--
--   bq query --use_legacy_sql=false --location=US \
--     --project_id=prd-utpbi-data-operation \
--     < qs_s3_gap_vaso/bigquery/tables/hist_queesmart_mp3_catalog_vaso.sql
-- =============================================================================

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.raw_queue_smart.hist_queesmart_mp3_catalog_vaso` (
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
  duration_seconds FLOAT64,
  sync_mode STRING,
  convert_method STRING,
  actual_format STRING,
  encoding STRING,
  segment_index INT64,
  segment_count INT64,
  segment_offset_seconds FLOAT64
)
PARTITION BY fecha_audio
OPTIONS (
  description = 'VASO: audios S3→GCS omitidos por regex legado (.audio o prefijo!=6). Job qs_s3_gap_vaso.'
);
