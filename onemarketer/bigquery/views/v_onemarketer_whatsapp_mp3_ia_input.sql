-- Vista de inspección: audios MP3 candidatos + contexto de chat (sin Gen IA).
-- Útil para validar URIs y filtros antes de ejecutar el SP.

CREATE OR REPLACE VIEW `${PROJECT_ID}.${DATASET_RAW}.v_onemarketer_whatsapp_mp3_ia_input` AS
SELECT
  mp3.fecha_evento AS process_date,
  mp3.gcs_uri,
  mp3.idcase,
  mp3.idmessage,
  mp3.waid,
  mp3.duration_seconds,
  mp3.file_name,
  mp3.conversion_status,
  chats.text AS chat_text,
  chats.origin AS chat_origin,
  chats.`user` AS chat_user,
  chats.category AS chat_category,
  chats.skill AS chat_skill,
  chats.time AS chat_time
FROM `${PROJECT_ID}.${DATASET_RAW}.reporte_whatsapp_mp3` AS mp3
LEFT JOIN `${PROJECT_ID}.${DATASET_RAW}.reporte_chats` AS chats
  ON chats.fecha_evento = mp3.fecha_evento
 AND chats.idcase = mp3.idcase
 AND chats.idmessage = mp3.idmessage
WHERE mp3.conversion_status IN ('OK', 'SKIPPED_EXISTS', 'SKIPPED_ALREADY_MP3')
  AND mp3.gcs_uri IS NOT NULL;
