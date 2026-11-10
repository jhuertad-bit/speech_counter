-- =============================================================================
-- Diagnóstico: lcra_* vacíos en reporteAtenciones (incidencia desde ~2026-06-29)
-- Proyecto: prd-utpbi-data-operation | Location: US
-- =============================================================================

-- 1) Serie diaria alrededor del corte
SELECT
  DATE(start_time) AS d,
  COUNT(*) AS n,
  COUNTIF(NULLIF(TRIM(CAST(lcra_lead AS STRING)), '') IS NULL) AS lead_vacio,
  COUNTIF(NULLIF(TRIM(CAST(lcra_dni AS STRING)), '') IS NULL) AS dni_vacio,
  COUNTIF(NULLIF(TRIM(CAST(lcra_celular_in AS STRING)), '') IS NULL) AS cel_vacio,
  COUNTIF(NULLIF(TRIM(CAST(lcra_postulante AS STRING)), '') IS NULL) AS postulante_vacio,
  ROUND(
    100 * COUNTIF(NULLIF(TRIM(CAST(lcra_dni AS STRING)), '') IS NULL) / COUNT(*),
    1
  ) AS pct_dni_vacio
FROM `prd-utpbi-data-operation.raw_onemarketer.reporteAtenciones`
WHERE DATE(start_time) BETWEEN DATE '2026-06-20' AND CURRENT_DATE('America/Lima')
GROUP BY 1
ORDER BY 1;

-- 2) Muestra post-corte (para comparar vs JSON landing GCS)
SELECT
  id_case,
  start_time,
  user_id,
  lcra_lead,
  lcra_dni,
  lcra_celular_in,
  lcra_postulante,
  lcra_campus,
  lcra_origen,
  lcra_tipo_cli,
  lcra_flujo
FROM `prd-utpbi-data-operation.raw_onemarketer.reporteAtenciones`
WHERE DATE(start_time) = DATE '2026-06-29'
LIMIT 20;

-- 3) Impacto en vista CRM lead
SELECT
  COUNT(*) AS n_casos,
  COUNTIF(dni_norm IS NULL AND cel_norm IS NULL) AS sin_llave_crm,
  COUNTIF(flag_lead_completo) AS lead_completo
FROM `prd-utpbi-data-operation.raw_onemarketer.v_onemarketer_caso_crm_lead`
WHERE case_date BETWEEN DATE '2026-06-29' AND CURRENT_DATE('America/Lima');
