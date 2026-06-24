-- Dataset RAW QueeSmart (audios S3 → GCS → catálogo BQ)
-- Reemplazar ${PROJECT_ID} al desplegar.
--
-- Ejemplo PRD:
--   PROJECT_ID = prd-utpbi-data-operation
--   LOCATION   = us-central1  (GCS bucket + BigQuery)

CREATE SCHEMA IF NOT EXISTS `${PROJECT_ID}.raw_queuesmart`
OPTIONS (
  location = 'us-central1',
  description = 'Capa raw QueeSmart — catálogo de MP3 importados desde S3'
);
