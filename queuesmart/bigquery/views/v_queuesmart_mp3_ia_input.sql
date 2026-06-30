-- Vista de inspección: audios con GCS + contexto CRM (sin Gen IA).
-- Equivalente a v_onemarketer_whatsapp_mp3_ia_input para QueeSmart.

CREATE OR REPLACE VIEW `${PROJECT_ID}.${DATASET_RAW}.v_queuesmart_mp3_ia_input` AS
SELECT
  e.process_day,
  e.gcs_uri,
  e.file_name,
  e.audio,
  e.record_id,
  e.campus_code,
  e.type_code,
  e.match_status,
  e.cliente_tipo,
  e.cliente_estado,
  e.cliente_url,
  e.asesor_nombre,
  e.asesor_usuario,
  e.asesor_codigo,
  e.num_celular,
  e.enviado_sms,
  e.transferido,
  e.apellido_paterno,
  e.audio_fecha,
  e.file_size_bytes
FROM `${PROJECT_ID}.${DATASET_RAW}.queuesmart_mp3_enriched` AS e
WHERE e.match_status IN ('BOTH', 'GCS_ONLY')
  AND e.gcs_uri IS NOT NULL;
