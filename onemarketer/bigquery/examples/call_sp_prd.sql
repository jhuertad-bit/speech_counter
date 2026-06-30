-- Ejecutar en BigQuery (región US — mismo dataset del SP)

CALL `prd-utpbi-data-operation.adf_speech_analytics.sp_onemarketer_whatsapp_gen_ia`(
  DATE_SUB(CURRENT_DATE('America/Lima'), INTERVAL 1 DAY)
);

-- Validar salida
SELECT process_date, COUNT(*) AS n
FROM `prd-utpbi-data-operation.adf_speech_analytics.hist_onemarketer_whatsapp_gen_ia_process_data_prd`
WHERE process_date >= DATE_SUB(CURRENT_DATE('America/Lima'), INTERVAL 7 DAY)
GROUP BY 1
ORDER BY 1 DESC;
