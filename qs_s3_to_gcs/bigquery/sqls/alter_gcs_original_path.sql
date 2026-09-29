-- Copia intacta del audio S3 en GCS: …/{fecha}/original/{source_file_name}
-- Ejecutar en US antes del redeploy del Job qs_s3_to_gcs.
-- source_file_name sigue siendo solo el basename (join tickets).
-- PRD
ALTER TABLE `prd-utpbi-data-operation.raw_queue_smart.hist_queesmart_mp3_catalog`
  ADD COLUMN IF NOT EXISTS gcs_original_uri STRING,
  ADD COLUMN IF NOT EXISTS gcs_original_path STRING;
