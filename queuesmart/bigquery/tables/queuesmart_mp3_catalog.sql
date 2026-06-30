-- Capa consolidada: catálogo MP3 (dedup por gcs_uri). Vaso de agua desde hist_queesmart_mp3_catalog.

CREATE TABLE IF NOT EXISTS `${PROJECT_ID}.${DATASET_RAW}.queuesmart_mp3_catalog` (
  process_day DATE NOT NULL,
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
  sync_mode STRING,
  load_date DATETIME
)
PARTITION BY process_day
OPTIONS (
  description = 'QueeSmart MP3 en GCS — capa consolidada (dedup por gcs_uri)'
);
