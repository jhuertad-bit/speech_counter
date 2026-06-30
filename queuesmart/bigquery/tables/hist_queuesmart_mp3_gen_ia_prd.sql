-- Gen IA QueeSmart MP3 — capa consumo — PRODUCCIÓN
-- prd-utpbi-data-operation.adf_speech_analytics (US) | fuente: hist_queesmart_mp3_catalog

CREATE TABLE IF NOT EXISTS `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_prd` (
  process_date DATE,
  gcs_uri STRING,
  file_name STRING,
  campus_code STRING,
  type_code STRING,
  correlative STRING,
  file_size_bytes INT64,
  transcripcion STRING,
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
  description = 'Gen IA QueeSmart MP3 (catálogo S3→GCS) — capa prd / consumo'
);
