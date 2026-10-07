-- Vista de inspección: audios con GCS + contexto ticket (sin Gen IA).
-- Equivalente a v_onemarketer_whatsapp_mp3_ia_input para QueeSmart.
-- Desplegar con --location=us-central1

CREATE OR REPLACE VIEW `prd-utpbi-data-operation.raw_queue_smart.v_queuesmart_mp3_ia_input` AS
SELECT
  e.process_day,
  e.gcs_uri,
  e.file_name,
  e.source_file_name,
  e.audio,
  e.recordid,
  e.rowid,
  e.codagencia,
  e.campus_code,
  e.type_code,
  e.correlative,
  e.match_status,
  e.asesornombre,
  e.asesorusuario,
  e.asesorcodigo,
  e.ndoc,
  e.nombresusuario,
  e.numcelular,
  e.clientetipo,
  e.clienteestado,
  e.creationtimestamp,
  e.starttimestamp,
  e.endtimestamp,
  e.`database`,
  e.file_size_bytes,
  e.duration_seconds,
  e.convert_method
FROM `prd-utpbi-data-operation.raw_queue_smart.queuesmart_mp3_enriched` AS e
WHERE e.match_status IN ('BOTH', 'GCS_ONLY')
  AND e.gcs_uri IS NOT NULL;
