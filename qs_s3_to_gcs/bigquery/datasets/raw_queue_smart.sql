-- Dataset RAW QueeSmart (audios S3 → GCS → catálogo BQ)
-- Reemplazar ${PROJECT_ID} al desplegar.
--
-- Ejemplo PRD:
--   PROJECT_ID = prd-utpbi-data-operation
--   LOCATION   = us-central1  (GCS bucket + BigQuery)

CREATE SCHEMA IF NOT EXISTS `${PROJECT_ID}.raw_queue_smart`
OPTIONS (
  location = 'US',
  description = 'Capa raw QueeSmart — catálogo MP3, tickets, sys_prompts, enriched'
);
