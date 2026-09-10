-- Columnas nuevas del Job (formato real). NO renombra rutas/tablas *mp3*.
-- Ejecutar en US antes del redeploy del Job.

ALTER TABLE `prd-utpbi-data-operation.raw_queue_smart.hist_queesmart_mp3_catalog`
  ADD COLUMN IF NOT EXISTS duration_seconds FLOAT64,
  ADD COLUMN IF NOT EXISTS actual_format STRING,
  ADD COLUMN IF NOT EXISTS encoding STRING;
