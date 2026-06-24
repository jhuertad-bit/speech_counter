-- Vista puente: detalle por CASO (drill-down desde v_onemarketer_lead_conversaciones).
--
-- lcra_lead NO es leadid: en prod suele ser etiqueta de flujo ("Lead Completo").
-- Cruces:
--   1) lcra_dni          ↔ leads.onetoone_nro
--   2) teléfono WA/bot   ↔ leads.mobilephone  (últimos 9 dígitos, sin +51)
--
-- Gen IA (opcional): último audio OK del caso desde hist_..._prd.
--
-- Placeholders: ${PROJECT_ID}, ${DATASET_RAW}, ${CRM_PROJECT}, ${CRM_DATASET}

CREATE OR REPLACE VIEW `${PROJECT_ID}.${DATASET_RAW}.v_onemarketer_caso_crm_lead` AS
WITH casos AS (
  SELECT
    SAFE_CAST(id_case AS INT64) AS idcase,
    id_case,
    start_time,
    end_time,
    channel,
    skill,
    category_description,
    user_id,
    lcra_lead,
    lcra_flujo_completo,
    lcra_dni,
    lcra_celular_in,
    lcra_postulante,
    lcra_campus,
    lcra_origen,
    lcra_tipo_cli,
    lcra_edad,
    intent_list,
    agent_open,
    agent_close,
    DATE(start_time) AS case_date
  FROM `${PROJECT_ID}.${DATASET_RAW}.reporteAtenciones`
  WHERE id_case IS NOT NULL
),
casos_norm AS (
  SELECT
    c.*,
    NULLIF(REGEXP_REPLACE(TRIM(c.lcra_dni), r'[^0-9]', ''), '') AS dni_norm,
    NULLIF(
      RIGHT(
        REGEXP_REPLACE(
          REGEXP_REPLACE(TRIM(COALESCE(c.lcra_celular_in, c.user_id)), r'[^0-9]', ''),
          r'^51',
          ''
        ),
        9
      ),
      ''
    ) AS phone_norm,
    (c.lcra_lead = 'Lead Completo') AS flag_lead_completo
  FROM casos AS c
),
leads_snap AS (
  SELECT
    l.*,
    ROW_NUMBER() OVER (
      PARTITION BY l.leadid
      ORDER BY l.process_day DESC, l.modifiedon DESC NULLS LAST
    ) AS rn_lead
  FROM `${CRM_PROJECT}.${CRM_DATASET}.leads` AS l
),
leads_latest AS (
  SELECT
    leadid,
    process_day,
    fullname,
    firstname,
    lastname,
    emailaddress1,
    mobilephone,
    createdon,
    modifiedon,
    onetoone_nro,
    onetoone_fechadenacimiento,
    onetoone_fuenteorigen,
    onetoone_detallefuenteorigen,
    onetoone_sededeseada,
    onetoone_sedeeducativa,
    onetoone_clasificacion,
    utp_nombre_campana_digital,
    utp_proveedor_digital,
    NULLIF(REGEXP_REPLACE(TRIM(onetoone_nro), r'[^0-9]', ''), '') AS dni_norm,
    NULLIF(
      RIGHT(
        REGEXP_REPLACE(
          REGEXP_REPLACE(TRIM(mobilephone), r'[^0-9]', ''),
          r'^51',
          ''
        ),
        9
      ),
      ''
    ) AS phone_norm
  FROM leads_snap
  WHERE rn_lead = 1
),
gen_ia_caso AS (
  SELECT
    idcase,
    ARRAY_AGG(
      STRUCT(
        idmessage,
        gcs_uri,
        transcripcion,
        resumen,
        intencion,
        tono,
        duration_seconds
      )
      ORDER BY duration_seconds DESC NULLS LAST
      LIMIT 1
    )[OFFSET(0)] AS ia
  FROM `${PROJECT_ID}.${DATASET_ANALYTICS}.hist_onemarketer_whatsapp_gen_ia_process_data_prd`
  WHERE idcase IS NOT NULL
  GROUP BY idcase
),
matched AS (
  SELECT
    c.*,
    l.leadid,
    l.fullname AS crm_fullname,
    l.emailaddress1 AS crm_email,
    l.mobilephone AS crm_mobilephone,
    l.onetoone_nro AS crm_dni,
    l.onetoone_sededeseada AS crm_sede_deseada,
    l.onetoone_fuenteorigen AS crm_fuente_origen,
    l.onetoone_clasificacion AS crm_clasificacion,
    l.utp_nombre_campana_digital AS crm_campana_digital,
    l.createdon AS crm_createdon,
    l.modifiedon AS crm_modifiedon,
    CASE
      WHEN c.dni_norm IS NOT NULL AND c.dni_norm = l.dni_norm THEN 'dni'
      WHEN c.phone_norm IS NOT NULL AND c.phone_norm = l.phone_norm THEN 'telefono'
      ELSE NULL
    END AS match_method,
    ABS(TIMESTAMP_DIFF(c.start_time, l.createdon, SECOND)) AS match_time_delta_sec
  FROM casos_norm AS c
  LEFT JOIN leads_latest AS l
    ON (
      c.dni_norm IS NOT NULL
      AND l.dni_norm IS NOT NULL
      AND c.dni_norm = l.dni_norm
    )
    OR (
      (c.dni_norm IS NULL OR c.dni_norm = '')
      AND c.phone_norm IS NOT NULL
      AND l.phone_norm IS NOT NULL
      AND c.phone_norm = l.phone_norm
    )
),
matched_best AS (
  SELECT * EXCEPT(rn_match)
  FROM (
    SELECT
      m.*,
      ROW_NUMBER() OVER (
        PARTITION BY m.idcase, m.start_time
        ORDER BY
          CASE m.match_method WHEN 'dni' THEN 1 WHEN 'telefono' THEN 2 ELSE 9 END,
          m.match_time_delta_sec ASC NULLS LAST
      ) AS rn_match
    FROM matched AS m
    WHERE m.match_method IS NOT NULL
  )
  WHERE rn_match = 1

  UNION ALL

  SELECT
    c.*,
    CAST(NULL AS STRING) AS leadid,
    CAST(NULL AS STRING) AS crm_fullname,
    CAST(NULL AS STRING) AS crm_email,
    CAST(NULL AS STRING) AS crm_mobilephone,
    CAST(NULL AS STRING) AS crm_dni,
    CAST(NULL AS STRING) AS crm_sede_deseada,
    CAST(NULL AS STRING) AS crm_fuente_origen,
    CAST(NULL AS STRING) AS crm_clasificacion,
    CAST(NULL AS STRING) AS crm_campana_digital,
    CAST(NULL AS TIMESTAMP) AS crm_createdon,
    CAST(NULL AS TIMESTAMP) AS crm_modifiedon,
    CAST(NULL AS STRING) AS match_method,
    CAST(NULL AS INT64) AS match_time_delta_sec
  FROM casos_norm AS c
  WHERE NOT EXISTS (
    SELECT 1
    FROM matched AS m
    WHERE m.idcase = c.idcase
      AND m.start_time = c.start_time
      AND m.match_method IS NOT NULL
  )
)
SELECT
  m.idcase,
  m.id_case,
  m.case_date,
  m.start_time,
  m.end_time,
  m.channel,
  m.skill,
  m.category_description,
  m.user_id,
  m.lcra_lead,
  m.flag_lead_completo,
  m.lcra_flujo_completo,
  m.lcra_dni,
  m.lcra_celular_in,
  m.lcra_postulante,
  m.lcra_campus,
  m.lcra_origen,
  m.lcra_tipo_cli,
  m.dni_norm,
  m.phone_norm,
  m.leadid,
  m.match_method,
  m.match_time_delta_sec,
  m.crm_fullname,
  m.crm_email,
  m.crm_mobilephone,
  m.crm_dni,
  m.crm_sede_deseada,
  m.crm_fuente_origen,
  m.crm_clasificacion,
  m.crm_campana_digital,
  m.crm_createdon,
  m.crm_modifiedon,
  g.ia.idmessage AS ia_idmessage,
  g.ia.gcs_uri AS ia_gcs_uri,
  g.ia.transcripcion AS ia_transcripcion,
  g.ia.resumen AS ia_resumen,
  g.ia.intencion AS ia_intencion,
  g.ia.tono AS ia_tono,
  g.ia.duration_seconds AS ia_duration_seconds
FROM matched_best AS m
LEFT JOIN gen_ia_caso AS g
  ON g.idcase = m.idcase;
