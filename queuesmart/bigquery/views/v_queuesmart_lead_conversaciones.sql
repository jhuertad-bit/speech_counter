-- Vista Counter a nivel LEAD: un registro por leadid con los audios de QueeSmart.
-- Fuente: v_queuesmart_counter_crm_lead (mismas uniones Dynamics que Genesys).
-- Proyecto fijo de prod: prd-utpbi-data-operation.
-- Desplegar con --location=us-central1

CREATE OR REPLACE VIEW `prd-utpbi-data-operation.raw_queue_smart.v_queuesmart_lead_conversaciones` AS
SELECT
  leadid,
  ANY_VALUE(crm_fullname) AS crm_fullname,
  ANY_VALUE(crm_email) AS crm_email,
  ANY_VALUE(crm_mobilephone) AS crm_mobilephone,
  ANY_VALUE(crm_dni) AS crm_dni,
  ANY_VALUE(crm_sede_deseada) AS crm_sede_deseada,
  ANY_VALUE(crm_fuente_origen) AS crm_fuente_origen,
  ANY_VALUE(crm_clasificacion) AS crm_clasificacion,
  ANY_VALUE(crm_campana_digital) AS crm_campana_digital,
  ANY_VALUE(crm_createdon) AS crm_createdon,
  ANY_VALUE(crm_modifiedon) AS crm_modifiedon,
  ANY_VALUE(crm_producto_carrera) AS crm_producto_carrera,
  ANY_VALUE(crm_sub_grado) AS crm_sub_grado,
  ANY_VALUE(crm_detalle_fuente_origen_name) AS crm_detalle_fuente_origen_name,
  ANY_VALUE(crm_sede_deseada_name) AS crm_sede_deseada_name,
  ANY_VALUE(crm_telefono_alterno) AS crm_telefono_alterno,
  ANY_VALUE(utp_primera_tipificacion_exitosa) AS utp_primera_tipificacion_exitosa,
  ANY_VALUE(utp_segundaactividadexitosa) AS utp_segundaactividadexitosa,
  ANY_VALUE(utp_ultima_actividad_exitosa) AS utp_ultima_actividad_exitosa,
  ANY_VALUE(utp_ultimatipificacion) AS utp_ultimatipificacion,
  ANY_VALUE(crm_fecha_nacimiento) AS crm_fecha_nacimiento,
  ANY_VALUE(parentcontactid) AS parentcontactid,
  ANY_VALUE(yomifullname) AS yomifullname,
  ANY_VALUE(crm_usuario_primera_actividad_exitosa) AS crm_usuario_primera_actividad_exitosa,
  ANY_VALUE(crm_equipo_de_trabajo) AS crm_equipo_de_trabajo,
  ANY_VALUE(crm_supervisor_asignado) AS crm_supervisor_asignado,
  ANY_VALUE(ownerid) AS ownerid,
  ANY_VALUE(owneridname) AS owneridname,
  ANY_VALUE(owneridyominame) AS owneridyominame,
  ANY_VALUE(customerid) AS customerid,
  COUNT(DISTINCT audio_key) AS total_audios_counter,
  COUNT(DISTINCT COALESCE(audio_fecha, process_day)) AS total_dias_con_audio,
  MIN(COALESCE(audio_fecha, process_day)) AS primer_audio_date,
  MAX(COALESCE(audio_fecha, process_day)) AS ultimo_audio_date,
  COUNTIF(match_method = 'dni') AS audios_match_dni,
  COUNTIF(match_method = 'telefono') AS audios_match_telefono,
  COUNTIF(ia_intencion IS NOT NULL) AS total_audios_gen_ia,
  ARRAY_AGG(DISTINCT ia_intencion IGNORE NULLS) AS intenciones_ia,
  STRING_AGG(DISTINCT campus_code, ', ' ORDER BY campus_code) AS campuses,
  STRING_AGG(DISTINCT asesornombre, ', ' ORDER BY asesornombre) AS asesores
FROM `prd-utpbi-data-operation.raw_queue_smart.v_queuesmart_counter_crm_lead`
WHERE leadid IS NOT NULL
GROUP BY leadid;
