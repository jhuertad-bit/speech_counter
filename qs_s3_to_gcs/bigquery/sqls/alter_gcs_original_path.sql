-- Copia intacta del audio S3 en GCS: …/{fecha}/original/{source_file_name}
-- Ejecutar en US (PRD) antes del redeploy / backfill.
-- source_file_name sigue siendo solo el basename (join tickets).

ALTER TABLE `prd-utpbi-data-operation.raw_queue_smart.hist_queesmart_mp3_catalog`
  ADD COLUMN IF NOT EXISTS gcs_original_uri STRING,
  ADD COLUMN IF NOT EXISTS gcs_original_path STRING;
