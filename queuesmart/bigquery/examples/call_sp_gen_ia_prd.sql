-- PRD: Gen IA directo sobre hist_queesmart_mp3_catalog (después de qs_s3_to_gcs)

DECLARE v_fecha DATE DEFAULT DATE_SUB(CURRENT_DATE('America/Lima'), INTERVAL 1 DAY);

-- Candidatos del día
SELECT COUNT(*) AS audios_catalogo
FROM `prd-utpbi-data-operation.raw_queuesmart.v_hist_queesmart_mp3_catalog_ia_input`
WHERE process_date = v_fecha;

-- Gen IA
CALL `prd-utpbi-data-operation.adf_speech_analytics.sp_queuesmart_mp3_gen_ia`(v_fecha);

-- Resultados
SELECT
  process_date,
  COUNT(*) AS n
FROM `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_prd`
WHERE process_date = v_fecha
GROUP BY 1;

SELECT
  file_name,
  campus_code,
  type_code,
  LEFT(transcripcion, 120) AS transcripcion_preview,
  resumen,
  intencion
FROM `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_prd`
WHERE process_date = v_fecha
LIMIT 20;
