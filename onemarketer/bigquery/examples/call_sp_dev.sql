-- Ejemplo manual (dev). Ajustar fecha.
CALL `dev-utpbi-data-operation.adf_speech_analytics.sp_onemarketer_whatsapp_gen_ia`(
  DATE '2026-06-09'
);

-- Validar insumos antes del CALL:
SELECT *
FROM `dev-utpbi-data-operation.raw_onemarketer.v_onemarketer_whatsapp_mp3_ia_input`
WHERE process_date = '2026-06-09'
LIMIT 20;

-- Validar salida:
SELECT process_date, idcase, idmessage, intencion, LEFT(transcripcion, 200) AS transcripcion_preview
FROM `dev-utpbi-data-operation.adf_speech_analytics.hist_onemarketer_whatsapp_gen_ia_process_data_prd`
WHERE process_date = '2026-06-09'
LIMIT 20;
