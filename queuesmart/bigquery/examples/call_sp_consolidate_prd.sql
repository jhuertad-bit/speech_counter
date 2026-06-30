-- PRD: consolidar ayer (Lima) con ventana de 3 días hacia atrás.

DECLARE v_fecha DATE DEFAULT DATE_SUB(CURRENT_DATE('America/Lima'), INTERVAL 1 DAY);

CALL `prd-utpbi-data-operation.raw_queuesmart.sp_queuesmart_mp3_consolidate`(v_fecha);

-- Validar conteos
SELECT
  v_fecha AS fecha_proceso,
  (SELECT COUNT(*) FROM `prd-utpbi-data-operation.raw_queuesmart.queuesmart_mp3_catalog`
   WHERE process_day BETWEEN DATE_SUB(v_fecha, INTERVAL 3 DAY) AND v_fecha) AS catalog_rows,
  (SELECT COUNT(*) FROM `prd-utpbi-data-operation.raw_queuesmart.queuesmart_ticketero_crm`
   WHERE process_day BETWEEN DATE_SUB(v_fecha, INTERVAL 3 DAY) AND v_fecha) AS crm_rows,
  (SELECT COUNT(*) FROM `prd-utpbi-data-operation.raw_queuesmart.queuesmart_mp3_enriched`
   WHERE process_day BETWEEN DATE_SUB(v_fecha, INTERVAL 3 DAY) AND v_fecha) AS enriched_rows,
  (SELECT COUNT(*) FROM `prd-utpbi-data-operation.raw_queuesmart.queuesmart_mp3_enriched`
   WHERE process_day BETWEEN DATE_SUB(v_fecha, INTERVAL 3 DAY) AND v_fecha
     AND match_status = 'BOTH') AS matched_both;
