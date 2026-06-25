-- Catálogo de audios QueeSmart (S3 → GCS) — PRODUCCIÓN
-- Proyecto: prd-utpbi-data-operation | Dataset: raw_queuesmart (us-central1)

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.raw_queuesmart.hist_queesmart_mp3_catalog` (
  fecha_audio DATE NOT NULL,
  fecha_procesamiento TIMESTAMP NOT NULL,
  file_name STRING NOT NULL,
  gcs_uri STRING NOT NULL,
  gcs_path STRING,
  campus_code STRING,
  type_code STRING,
  correlative STRING,
  s3_uri STRING,
  s3_key STRING,
  file_size_bytes INT64,
  sync_mode STRING
)
PARTITION BY fecha_audio
OPTIONS (
  description = 'Catálogo de MP3 QueeSmart importados desde S3 a GCS (metadatos por archivo)'
);
