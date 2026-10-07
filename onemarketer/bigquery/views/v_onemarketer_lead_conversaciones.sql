-- Vista a nivel LEAD: un registro por leadid CRM con métricas agregadas de OneMarketer.
--
-- Cruce CRM en prod: prd-utpbi-data-storage-pv.raw_dynamic_crm.
--
-- OneMarketer no trae contact_id, así que el lead no se une por leadid como Genesys.
-- A partir del lead, las uniones son las mismas que Genesys:
--   1) lcra_dni        ↔ leads.onetoone_nro
--   2) teléfono WA/bot ↔ leads.mobilephone (9 dígitos PE)
--   3) leads.utp_usuario_primera_actividad_exitosa ↔ systemusers.systemuserid
--   4) leads.parentcontactid ↔ opportunities.customerid
-- systemusers y opportunities: snapshot más reciente por llave.
--
-- Detalle por caso: v_onemarketer_caso_crm_lead
-- Proyecto fijo de prod: prd-utpbi-data-operation / prd-utpbi-data-storage-pv.

CREATE OR REPLACE VIEW `prd-utpbi-data-operation.raw_onemarketer.v_onemarketer_lead_conversaciones` AS
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
  FROM `prd-utpbi-data-operation.raw_onemarketer.reporteAtenciones`
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
      ORDER BY l.modifiedon DESC NULLS LAST
    ) AS rn_lead
  FROM `prd-utpbi-data-storage-pv.raw_dynamic_crm.leads` AS l
),
leads_latest AS (
  SELECT
    leadid,
    fullname AS crm_fullname,
    firstname AS crm_firstname,
    lastname AS crm_lastname,
    emailaddress1 AS crm_email,
    mobilephone AS crm_mobilephone,
    SAFE_CAST(createdon AS TIMESTAMP) AS crm_createdon,
    modifiedon AS crm_modifiedon,
    onetoone_nro AS crm_dni,
    onetoone_fechadenacimiento AS crm_fecha_nacimiento,
    onetoone_fuenteorigen AS crm_fuente_origen,
    onetoone_detallefuenteorigen AS crm_detalle_fuente_origen,
    onetoone_sededeseada AS crm_sede_deseada,
    onetoone_sedeeducativa AS crm_sede_educativa,
    onetoone_clasificacion AS crm_clasificacion,
    utp_nombre_campana_digital AS crm_campana_digital,
    onetoone_productoname AS crm_producto_carrera,
    utp_sub_gradoname AS crm_sub_grado,
    onetoone_detallefuenteorigenname AS crm_detalle_fuente_origen_name,
    onetoone_sededeseadaname AS crm_sede_deseada_name,
    telephone2 AS crm_telefono_alterno,
    utp_primera_tipificacion_exitosa,
    utp_segundaactividadexitosa,
    utp_ultima_actividad_exitosa,
    utp_ultimatipificacion,
    parentcontactid,
    yomifullname,
    utp_usuario_primera_actividad_exitosa,
    utp_usuario_primera_actividad_exitosaname AS crm_usuario_primera_actividad_exitosa,
    NULLIF(REGEXP_REPLACE(TRIM(SAFE_CAST(onetoone_nro AS STRING)), r'[^0-9]', ''), '') AS dni_norm,
    NULLIF(
      RIGHT(
        REGEXP_REPLACE(
          REGEXP_REPLACE(TRIM(SAFE_CAST(mobilephone AS STRING)), r'[^0-9]', ''),
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
systemusers_latest AS (
  SELECT * EXCEPT(rn_user)
  FROM (
    SELECT
      su.systemuserid,
      su.utp_equipo_trabajoname,
      su.utp_supervisorasignadoidname,
      ROW_NUMBER() OVER (
        PARTITION BY su.systemuserid
        ORDER BY su.modifiedon DESC NULLS LAST
      ) AS rn_user
    FROM `prd-utpbi-data-storage-pv.raw_dynamic_crm.systemusers` AS su
  )
  WHERE rn_user = 1
),
opportunities_latest AS (
  SELECT * EXCEPT(rn_opp)
  FROM (
    SELECT
      op.customerid,
      op.ownerid,
      op.owneridMicrosoft_Dynamics_CRM_associatednavigationproperty,
      op.owneridMicrosoft_Dynamics_CRM_lookuplogicalname,
      op.owneridname,
      op.owneridtype,
      op.owneridyominame,
      ROW_NUMBER() OVER (
        PARTITION BY op.customerid
        ORDER BY op.modifiedon DESC NULLS LAST
      ) AS rn_opp
    FROM `prd-utpbi-data-storage-pv.raw_dynamic_crm.opportunities` AS op
  )
  WHERE rn_opp = 1
),
leads_crm AS (
  SELECT
    l.*,
    su.utp_equipo_trabajoname AS crm_equipo_de_trabajo,
    su.utp_supervisorasignadoidname AS crm_supervisor_asignado,
    op.ownerid,
    op.owneridMicrosoft_Dynamics_CRM_associatednavigationproperty,
    op.owneridMicrosoft_Dynamics_CRM_lookuplogicalname,
    op.owneridname,
    op.owneridtype,
    op.owneridyominame,
    op.customerid
  FROM leads_latest AS l
  LEFT JOIN systemusers_latest AS su
    ON UPPER(l.utp_usuario_primera_actividad_exitosa) = UPPER(su.systemuserid)
  LEFT JOIN opportunities_latest AS op
    ON UPPER(l.parentcontactid) = UPPER(op.customerid)
),
caso_lead_match AS (
  SELECT * EXCEPT(rn_match)
  FROM (
    SELECT
      c.*,
      l.leadid,
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
      l.crm_producto_carrera,
      l.crm_sub_grado,
      l.crm_detalle_fuente_origen_name,
      l.crm_sede_deseada_name,
      l.crm_telefono_alterno,
      l.utp_primera_tipificacion_exitosa,
      l.utp_segundaactividadexitosa,
      l.utp_ultima_actividad_exitosa,
      l.utp_ultimatipificacion,
      l.parentcontactid,
      l.yomifullname,
      l.crm_usuario_primera_actividad_exitosa,
      l.crm_equipo_de_trabajo,
      l.crm_supervisor_asignado,
      l.ownerid,
      l.owneridMicrosoft_Dynamics_CRM_associatednavigationproperty,
      l.owneridMicrosoft_Dynamics_CRM_lookuplogicalname,
      l.owneridname,
      l.owneridtype,
      l.owneridyominame,
      l.customerid,
      CASE
        WHEN c.dni_norm IS NOT NULL AND c.dni_norm = l.dni_norm THEN 'dni'
        WHEN c.phone_norm IS NOT NULL AND c.phone_norm = l.phone_norm THEN 'telefono'
        ELSE NULL
      END AS match_method,
      ABS(TIMESTAMP_DIFF(c.start_time, SAFE_CAST(l.crm_createdon AS TIMESTAMP), SECOND)) AS match_time_delta_sec,
      ROW_NUMBER() OVER (
        PARTITION BY c.idcase, c.start_time
        ORDER BY
          CASE
            WHEN c.dni_norm IS NOT NULL AND c.dni_norm = l.dni_norm THEN 1
            WHEN c.phone_norm IS NOT NULL AND c.phone_norm = l.phone_norm THEN 2
            ELSE 9
          END,
          ABS(TIMESTAMP_DIFF(c.start_time, SAFE_CAST(l.crm_createdon AS TIMESTAMP), SECOND)) ASC NULLS LAST
      ) AS rn_match
    FROM casos_norm AS c
    INNER JOIN leads_crm AS l
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
  FROM `prd-utpbi-data-operation.adf_speech_analytics.hist_onemarketer_whatsapp_gen_ia_process_data_prd`
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
  ANY_VALUE(crm_producto_carrera) AS crm_producto_carrera,
  ANY_VALUE(crm_sub_grado) AS crm_sub_grado,
  ANY_VALUE(crm_detalle_fuente_origen_name) AS crm_detalle_fuente_origen_name,
  ANY_VALUE(crm_sede_deseada_name) AS crm_sede_deseada_name,
  ANY_VALUE(crm_telefono_alterno) AS crm_telefono_alterno,
  ANY_VALUE(utp_primera_tipificacion_exitosa) AS utp_primera_tipificacion_exitosa,
  ANY_VALUE(utp_segundaactividadexitosa) AS utp_segundaactividadexitosa,
  ANY_VALUE(utp_ultima_actividad_exitosa) AS utp_ultima_actividad_exitosa,
  ANY_VALUE(utp_ultimatipificacion) AS utp_ultimatipificacion,
  ANY_VALUE(parentcontactid) AS parentcontactid,
  ANY_VALUE(yomifullname) AS yomifullname,
  ANY_VALUE(crm_usuario_primera_actividad_exitosa) AS crm_usuario_primera_actividad_exitosa,
  ANY_VALUE(crm_equipo_de_trabajo) AS crm_equipo_de_trabajo,
  ANY_VALUE(crm_supervisor_asignado) AS crm_supervisor_asignado,
  ANY_VALUE(ownerid) AS ownerid,
  ANY_VALUE(owneridMicrosoft_Dynamics_CRM_associatednavigationproperty) AS owneridMicrosoft_Dynamics_CRM_associatednavigationproperty,
  ANY_VALUE(owneridMicrosoft_Dynamics_CRM_lookuplogicalname) AS owneridMicrosoft_Dynamics_CRM_lookuplogicalname,
  ANY_VALUE(owneridname) AS owneridname,
  ANY_VALUE(owneridtype) AS owneridtype,
  ANY_VALUE(owneridyominame) AS owneridyominame,
  ANY_VALUE(customerid) AS customerid,
  ANY_VALUE(crm_createdon) AS crm_createdon,
  ANY_VALUE(crm_modifiedon) AS crm_modifiedon,
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
