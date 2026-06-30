-- Vista a nivel LEAD: un registro por leadid CRM con métricas agregadas de OneMarketer.
--
-- Cruce CRM siempre vía ${CRM_PROJECT}.${CRM_DATASET}.leads (en dev usar prod:
--   CRM_PROJECT = prd-utpbi-data-storage-pv).
--
-- Match por caso → agregación por leadid:
--   1) lcra_dni        ↔ onetoone_nro
--   2) teléfono WA/bot ↔ mobilephone (9 dígitos PE)
--
-- Detalle por caso: v_onemarketer_caso_crm_lead
--
-- Placeholders: ${PROJECT_ID}, ${DATASET_RAW}, ${DATASET_ANALYTICS},
--               ${CRM_PROJECT}, ${CRM_DATASET}

CREATE OR REPLACE VIEW `${PROJECT_ID}.${DATASET_RAW}.v_onemarketer_lead_conversaciones` AS
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
    process_day AS crm_process_day,
    fullname AS crm_fullname,
    firstname AS crm_firstname,
    lastname AS crm_lastname,
    emailaddress1 AS crm_email,
    mobilephone AS crm_mobilephone,
    createdon AS crm_createdon,
    modifiedon AS crm_modifiedon,
    onetoone_nro AS crm_dni,
    onetoone_fechadenacimiento AS crm_fecha_nacimiento,
    onetoone_fuenteorigen AS crm_fuente_origen,
    onetoone_detallefuenteorigen AS crm_detalle_fuente_origen,
    onetoone_sededeseada AS crm_sede_deseada,
    onetoone_sedeeducativa AS crm_sede_educativa,
    onetoone_clasificacion AS crm_clasificacion,
    utp_nombre_campana_digital AS crm_campana_digital,
    utp_proveedor_digital AS crm_proveedor_digital,
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
caso_lead_match AS (
  SELECT * EXCEPT(rn_match)
  FROM (
    SELECT
      c.*,
      l.leadid,
      l.crm_process_day,
      l.crm_fullname,
      l.crm_firstname,
      l.crm_lastname,
      l.crm_email,
      l.crm_mobilephone,
      l.crm_createdon,
      l.crm_modifiedon,
      l.crm_dni,
      l.crm_fecha_nacimiento,
      l.crm_fuente_origen,
      l.crm_detalle_fuente_origen,
      l.crm_sede_deseada,
      l.crm_sede_educativa,
      l.crm_clasificacion,
      l.crm_campana_digital,
      l.crm_proveedor_digital,
      CASE
        WHEN c.dni_norm IS NOT NULL AND c.dni_norm = l.dni_norm THEN 'dni'
        WHEN c.phone_norm IS NOT NULL AND c.phone_norm = l.phone_norm THEN 'telefono'
        ELSE NULL
      END AS match_method,
      ABS(TIMESTAMP_DIFF(c.start_time, l.crm_createdon, SECOND)) AS match_time_delta_sec,
      ROW_NUMBER() OVER (
        PARTITION BY c.idcase, c.start_time
        ORDER BY
          CASE
            WHEN c.dni_norm IS NOT NULL AND c.dni_norm = l.dni_norm THEN 1
            WHEN c.phone_norm IS NOT NULL AND c.phone_norm = l.phone_norm THEN 2
            ELSE 9
          END,
          ABS(TIMESTAMP_DIFF(c.start_time, l.crm_createdon, SECOND)) ASC NULLS LAST
      ) AS rn_match
    FROM casos_norm AS c
    INNER JOIN leads_latest AS l
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
  )
  WHERE rn_match = 1
),
gen_ia AS (
  SELECT
    idcase,
    idmessage,
    gcs_uri,
    transcripcion,
    resumen,
    intencion,
    tono,
    duration_seconds,
    process_date AS ia_process_date
  FROM `${PROJECT_ID}.${DATASET_ANALYTICS}.hist_onemarketer_whatsapp_gen_ia_process_data_prd`
  WHERE idcase IS NOT NULL
),
caso_con_ia AS (
  SELECT
    m.*,
    g.idmessage AS ia_idmessage,
    g.transcripcion AS ia_transcripcion,
    g.resumen AS ia_resumen,
    g.intencion AS ia_intencion,
    g.tono AS ia_tono,
    g.duration_seconds AS ia_duration_seconds,
    g.ia_process_date
  FROM caso_lead_match AS m
  LEFT JOIN gen_ia AS g
    ON g.idcase = m.idcase
)
SELECT
  leadid,
  ANY_VALUE(crm_fullname) AS crm_fullname,
  ANY_VALUE(crm_firstname) AS crm_firstname,
  ANY_VALUE(crm_lastname) AS crm_lastname,
  ANY_VALUE(crm_email) AS crm_email,
  ANY_VALUE(crm_mobilephone) AS crm_mobilephone,
  ANY_VALUE(crm_dni) AS crm_dni,
  ANY_VALUE(crm_sede_deseada) AS crm_sede_deseada,
  ANY_VALUE(crm_sede_educativa) AS crm_sede_educativa,
  ANY_VALUE(crm_fuente_origen) AS crm_fuente_origen,
  ANY_VALUE(crm_detalle_fuente_origen) AS crm_detalle_fuente_origen,
  ANY_VALUE(crm_clasificacion) AS crm_clasificacion,
  ANY_VALUE(crm_campana_digital) AS crm_campana_digital,
  ANY_VALUE(crm_proveedor_digital) AS crm_proveedor_digital,
  ANY_VALUE(crm_createdon) AS crm_createdon,
  ANY_VALUE(crm_modifiedon) AS crm_modifiedon,
  ANY_VALUE(crm_process_day) AS crm_process_day,
  COUNT(DISTINCT idcase) AS total_casos_onemarketer,
  COUNT(DISTINCT case_date) AS total_dias_con_caso,
  MIN(start_time) AS primera_conversacion_at,
  MAX(COALESCE(end_time, start_time)) AS ultima_conversacion_at,
  MIN(case_date) AS primera_conversacion_date,
  MAX(case_date) AS ultima_conversacion_date,
  COUNTIF(flag_lead_completo) AS casos_lead_completo,
  COUNTIF(NOT flag_lead_completo OR lcra_lead IS NULL) AS casos_sin_lead_completo,
  COUNT(DISTINCT channel) AS canales_distintos,
  STRING_AGG(DISTINCT channel, ', ' ORDER BY channel) AS canales,
  STRING_AGG(DISTINCT skill, ', ' ORDER BY skill) AS skills,
  STRING_AGG(DISTINCT category_description, ' | ' ORDER BY category_description) AS tipificaciones,
  COUNTIF(match_method = 'dni') AS casos_match_dni,
  COUNTIF(match_method = 'telefono') AS casos_match_telefono,
  COUNT(DISTINCT ia_idmessage) AS total_audios_gen_ia,
  ARRAY_AGG(DISTINCT ia_intencion IGNORE NULLS) AS intenciones_ia,
  ARRAY_AGG(
    STRUCT(
      idcase,
      case_date,
      channel,
      match_method,
      flag_lead_completo,
      ia_intencion,
      ia_tono,
      LEFT(ia_transcripcion, 300) AS transcripcion_preview
    )
    ORDER BY start_time DESC
    LIMIT 20
  ) AS casos_recientes,
  ARRAY_AGG(DISTINCT idcase IGNORE NULLS ORDER BY idcase) AS idcases
FROM caso_con_ia
GROUP BY leadid;
