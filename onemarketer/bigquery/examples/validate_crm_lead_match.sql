-- Validar cruce OneMarketer ↔ CRM a nivel LEAD.
-- DEV: vista en dev-utpbi-data-operation, CRM leads en prd-utpbi-data-storage-pv.

-- 1) Leads con al menos un caso OneMarketer
SELECT
  COUNT(*) AS leads_con_conversacion,
  SUM(total_casos_onemarketer) AS casos_totales,
  SUM(total_audios_gen_ia) AS audios_ia_totales,
  SUM(casos_lead_completo) AS casos_lead_completo
FROM `dev-utpbi-data-operation.raw_onemarketer.v_onemarketer_lead_conversaciones`;

-- 2) Cobertura del match (a nivel caso vía vista detalle)
SELECT
  match_method,
  COUNT(*) AS casos
FROM `dev-utpbi-data-operation.raw_onemarketer.v_onemarketer_caso_crm_lead`
WHERE leadid IS NOT NULL
  AND case_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)
GROUP BY 1;

-- 3) Muestra por lead (prod onemarketer + prod CRM — cambiar PROJECT_ID si aplica)
SELECT
  leadid,
  crm_fullname,
  crm_campana_digital,
  crm_clasificacion,
  total_casos_onemarketer,
  casos_lead_completo,
  canales,
  total_audios_gen_ia,
  intenciones_ia,
  primera_conversacion_date,
  ultima_conversacion_date
FROM `prd-utpbi-data-operation.raw_onemarketer.v_onemarketer_lead_conversaciones`
WHERE ultima_conversacion_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY total_casos_onemarketer DESC
LIMIT 20;

-- 4) Drill-down: casos de un lead
SELECT
  idcase,
  case_date,
  channel,
  match_method,
  flag_lead_completo,
  ia_intencion,
  LEFT(ia_transcripcion, 120) AS transcripcion_preview
FROM `prd-utpbi-data-operation.raw_onemarketer.v_onemarketer_caso_crm_lead`
WHERE leadid = 'PEGAR-LEADID-GUID-AQUI'
ORDER BY start_time DESC;
