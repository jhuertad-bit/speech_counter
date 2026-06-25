-- Validar cruce MP3 GCS ↔ CRM y candidatos Gen IA

SELECT
  process_day,
  match_status,
  COUNT(*) AS n
FROM `dev-utpbi-data-operation.raw_queuesmart.queuesmart_mp3_enriched`
WHERE process_day >= DATE_SUB(CURRENT_DATE('America/Lima'), INTERVAL 7 DAY)
GROUP BY 1, 2
ORDER BY 1 DESC, 2;

-- Detalle con GCS listo para IA (equivalente onemarketer mp3_ia_input)
SELECT *
FROM `dev-utpbi-data-operation.raw_queuesmart.v_queuesmart_mp3_ia_input`
WHERE process_day = DATE_SUB(CURRENT_DATE('America/Lima'), INTERVAL 1 DAY)
LIMIT 20;

-- Sin match GCS (solo CRM)
SELECT audio, record_id, cliente_tipo, num_celular
FROM `dev-utpbi-data-operation.raw_queuesmart.queuesmart_mp3_enriched`
WHERE match_status = 'CRM_ONLY'
  AND process_day >= DATE_SUB(CURRENT_DATE('America/Lima'), INTERVAL 3 DAY)
LIMIT 20;
