-- Vista Counter (QueeSmart): un audio enriquecido con el mismo CRM Dynamics que Genesys.
--
-- Fuente: raw_queue_smart.queuesmart_mp3_enriched (esquema prod: tickets_hist_raw).
-- Counter no trae contact_id. El lead se resuelve así:
--   1) ndoc ↔ leads.onetoone_nro (DNI)
--   2) numcelular ↔ leads.mobilephone (últimos 9 dígitos, sin +51)
-- A partir del lead, las uniones son las de Genesys:
--   3) leads.utp_usuario_primera_actividad_exitosa ↔ systemusers.systemuserid
--   4) leads.parentcontactid ↔ opportunities.customerid
-- systemusers y opportunities: snapshot más reciente por llave (modifiedon).
--
-- Proyecto fijo de prod: prd-utpbi-data-operation / prd-utpbi-data-storage-pv.
-- Desplegar con --location=us-central1

CREATE OR REPLACE VIEW `prd-utpbi-data-operation.raw_queue_smart.v_queuesmart_counter_crm_lead` AS
WITH audios AS (
  SELECT
    e.process_day,
    e.match_status,
    e.gcs_uri,
    e.file_name,
    e.source_file_name,
    e.audio,
    e.recordid,
    e.rowid,
    e.codagencia,
    e.campus_code,
    e.type_code,
    e.correlative,
    e.file_size_bytes,
    e.duration_seconds,
    e.convert_method,
    e.clientetipo,
    e.clienteestado,
    e.asesornombre,
    e.asesorusuario,
    e.asesorcodigo,
    e.ndoc,
    e.nombresusuario,
    e.numcelular,
    e.clienteprimernombre,
    e.clienteapellidopaterno,
    e.creationtimestamp,
    e.starttimestamp,
    e.endtimestamp,
    e.`database`,
    DATE(COALESCE(e.starttimestamp, e.creationtimestamp, TIMESTAMP(e.process_day))) AS audio_fecha,
    COALESCE(SAFE_CAST(e.recordid AS STRING), e.gcs_uri, e.file_name) AS audio_key,
    NULLIF(REGEXP_REPLACE(TRIM(SAFE_CAST(e.ndoc AS STRING)), r'[^0-9]', ''), '') AS dni_norm,
    NULLIF(
      RIGHT(
        REGEXP_REPLACE(
          REGEXP_REPLACE(TRIM(SAFE_CAST(e.numcelular AS STRING)), r'[^0-9]', ''),
          r'^51',
          ''
        ),
        9
      ),
      ''
    ) AS phone_norm
  FROM `prd-utpbi-data-operation.raw_queue_smart.queuesmart_mp3_enriched` AS e
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
    fullname,
    emailaddress1,
    mobilephone,
    SAFE_CAST(createdon AS TIMESTAMP) AS createdon,
    modifiedon,
    onetoone_nro,
    onetoone_fuenteorigen,
    onetoone_sededeseada,
    onetoone_clasificacion,
    utp_nombre_campana_digital,
    onetoone_productoname,
    utp_sub_gradoname,
    onetoone_detallefuenteorigenname,
    onetoone_sededeseadaname,
    telephone2,
    utp_primera_tipificacion_exitosa,
    utp_segundaactividadexitosa,
    utp_ultima_actividad_exitosa,
    utp_ultimatipificacion,
    onetoone_fechadenacimiento,
    parentcontactid,
    yomifullname,
    utp_usuario_primera_actividad_exitosa,
    utp_usuario_primera_actividad_exitosaname,
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
    ON UPPER(SAFE_CAST(l.utp_usuario_primera_actividad_exitosa AS STRING))
     = UPPER(SAFE_CAST(su.systemuserid AS STRING))
  LEFT JOIN opportunities_latest AS op
    ON UPPER(SAFE_CAST(l.parentcontactid AS STRING))
     = UPPER(SAFE_CAST(op.customerid AS STRING))
),
crm_matched AS (
  SELECT
    a.*,
    SAFE_CAST(l.leadid AS STRING) AS leadid,
    SAFE_CAST(l.fullname AS STRING) AS crm_fullname,
    SAFE_CAST(l.emailaddress1 AS STRING) AS crm_email,
    SAFE_CAST(l.mobilephone AS STRING) AS crm_mobilephone,
    SAFE_CAST(l.onetoone_nro AS STRING) AS crm_dni,
    SAFE_CAST(l.onetoone_sededeseada AS STRING) AS crm_sede_deseada,
    SAFE_CAST(l.onetoone_fuenteorigen AS STRING) AS crm_fuente_origen,
    SAFE_CAST(l.onetoone_clasificacion AS STRING) AS crm_clasificacion,
    SAFE_CAST(l.utp_nombre_campana_digital AS STRING) AS crm_campana_digital,
    l.createdon AS crm_createdon,
    SAFE_CAST(l.modifiedon AS TIMESTAMP) AS crm_modifiedon,
    SAFE_CAST(l.onetoone_productoname AS STRING) AS crm_producto_carrera,
    SAFE_CAST(l.utp_sub_gradoname AS STRING) AS crm_sub_grado,
    SAFE_CAST(l.onetoone_detallefuenteorigenname AS STRING) AS crm_detalle_fuente_origen_name,
    SAFE_CAST(l.onetoone_sededeseadaname AS STRING) AS crm_sede_deseada_name,
    SAFE_CAST(l.telephone2 AS STRING) AS crm_telefono_alterno,
    SAFE_CAST(l.utp_primera_tipificacion_exitosa AS STRING) AS utp_primera_tipificacion_exitosa,
    SAFE_CAST(l.utp_segundaactividadexitosa AS STRING) AS utp_segundaactividadexitosa,
    SAFE_CAST(l.utp_ultima_actividad_exitosa AS STRING) AS utp_ultima_actividad_exitosa,
    SAFE_CAST(l.utp_ultimatipificacion AS STRING) AS utp_ultimatipificacion,
    SAFE_CAST(l.onetoone_fechadenacimiento AS STRING) AS crm_fecha_nacimiento,
    SAFE_CAST(l.parentcontactid AS STRING) AS parentcontactid,
    SAFE_CAST(l.yomifullname AS STRING) AS yomifullname,
    SAFE_CAST(l.utp_usuario_primera_actividad_exitosaname AS STRING) AS crm_usuario_primera_actividad_exitosa,
    SAFE_CAST(l.crm_equipo_de_trabajo AS STRING) AS crm_equipo_de_trabajo,
    SAFE_CAST(l.crm_supervisor_asignado AS STRING) AS crm_supervisor_asignado,
    SAFE_CAST(l.ownerid AS STRING) AS ownerid,
    SAFE_CAST(l.owneridMicrosoft_Dynamics_CRM_associatednavigationproperty AS STRING)
      AS owneridMicrosoft_Dynamics_CRM_associatednavigationproperty,
    SAFE_CAST(l.owneridMicrosoft_Dynamics_CRM_lookuplogicalname AS STRING)
      AS owneridMicrosoft_Dynamics_CRM_lookuplogicalname,
    SAFE_CAST(l.owneridname AS STRING) AS owneridname,
    SAFE_CAST(l.owneridtype AS STRING) AS owneridtype,
    SAFE_CAST(l.owneridyominame AS STRING) AS owneridyominame,
    SAFE_CAST(l.customerid AS STRING) AS customerid,
    CASE
      WHEN a.dni_norm IS NOT NULL AND a.dni_norm = l.dni_norm THEN 'dni'
      WHEN a.phone_norm IS NOT NULL AND a.phone_norm = l.phone_norm THEN 'telefono'
      ELSE NULL
    END AS match_method,
    ABS(
      TIMESTAMP_DIFF(
        TIMESTAMP(COALESCE(a.audio_fecha, a.process_day)),
        SAFE_CAST(l.createdon AS TIMESTAMP),
        SECOND
      )
    ) AS match_time_delta_sec
  FROM audios AS a
  LEFT JOIN leads_crm AS l
    ON (
      a.dni_norm IS NOT NULL
      AND l.dni_norm IS NOT NULL
      AND a.dni_norm = l.dni_norm
    )
    OR (
      (a.dni_norm IS NULL OR a.dni_norm = '')
      AND a.phone_norm IS NOT NULL
      AND l.phone_norm IS NOT NULL
      AND a.phone_norm = l.phone_norm
    )
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY a.audio_key
    ORDER BY
      CASE
        WHEN a.dni_norm IS NOT NULL AND a.dni_norm = l.dni_norm THEN 1
        WHEN a.phone_norm IS NOT NULL AND a.phone_norm = l.phone_norm THEN 2
        ELSE 9
      END,
      ABS(
        TIMESTAMP_DIFF(
          TIMESTAMP(COALESCE(a.audio_fecha, a.process_day)),
          SAFE_CAST(l.createdon AS TIMESTAMP),
          SECOND
        )
      ) ASC NULLS LAST
  ) = 1
),
gen_ia AS (
  SELECT * EXCEPT(rn)
  FROM (
    SELECT
      gcs_uri,
      transcripcion,
      resumen,
      intencion,
      tono,
      ROW_NUMBER() OVER (
        PARTITION BY gcs_uri
        ORDER BY process_date DESC, load_date DESC
      ) AS rn
    FROM `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_prd`
    WHERE gcs_uri IS NOT NULL
  )
  WHERE rn = 1
)
SELECT
  m.process_day,
  m.match_status,
  m.gcs_uri,
  m.file_name,
  m.source_file_name,
  m.audio,
  m.recordid,
  m.audio_key,
  m.rowid,
  m.codagencia,
  m.campus_code,
  m.type_code,
  m.correlative,
  m.file_size_bytes,
  m.duration_seconds,
  m.clientetipo,
  m.clienteestado,
  m.asesornombre,
  m.asesorusuario,
  m.asesorcodigo,
  m.ndoc,
  m.dni_norm,
  m.nombresusuario,
  m.numcelular,
  m.phone_norm,
  m.clienteprimernombre,
  m.clienteapellidopaterno,
  m.audio_fecha,
  m.creationtimestamp,
  m.starttimestamp,
  m.endtimestamp,
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
  m.crm_producto_carrera,
  m.crm_sub_grado,
  m.crm_detalle_fuente_origen_name,
  m.crm_sede_deseada_name,
  m.crm_telefono_alterno,
  m.utp_primera_tipificacion_exitosa,
  m.utp_segundaactividadexitosa,
  m.utp_ultima_actividad_exitosa,
  m.utp_ultimatipificacion,
  m.crm_fecha_nacimiento,
  m.parentcontactid,
  m.yomifullname,
  m.crm_usuario_primera_actividad_exitosa,
  m.crm_equipo_de_trabajo,
  m.crm_supervisor_asignado,
  m.ownerid,
  m.owneridMicrosoft_Dynamics_CRM_associatednavigationproperty,
  m.owneridMicrosoft_Dynamics_CRM_lookuplogicalname,
  m.owneridname,
  m.owneridtype,
  m.owneridyominame,
  m.customerid,
  g.transcripcion AS ia_transcripcion,
  g.resumen AS ia_resumen,
  g.intencion AS ia_intencion,
  g.tono AS ia_tono
FROM crm_matched AS m
LEFT JOIN gen_ia AS g
  ON g.gcs_uri = m.gcs_uri;
