-- =============================================================================
-- SP: Consolidación QueeSmart MP3 (patrón Genesys "vaso de agua") — PRODUCCIÓN
--
-- Proyecto: prd-utpbi-data-operation
-- Dataset:  raw_queuesmart (us-central1)
--
-- Ventana: [p_fecha_proceso - 3 días, p_fecha_proceso]
--  1.1 Catálogo MP3 (hist → queuesmart_mp3_catalog), dedup por gcs_uri
--  1.2 CRM Ticketero (hist → queuesmart_ticketero_crm), dedup por record_id
--  1.3 Enriquecido GCS + CRM (→ queuesmart_mp3_enriched), join por audio = file_name
--
-- Ejecutar (diario, después de qs_s3_to_gcs + qs_sql_to_bq):
--   CALL `prd-utpbi-data-operation.raw_queuesmart.sp_queuesmart_mp3_consolidate`(
--     DATE_SUB(CURRENT_DATE('America/Lima'), INTERVAL 1 DAY)
--   );
-- =============================================================================

CREATE OR REPLACE PROCEDURE `prd-utpbi-data-operation.raw_queuesmart.sp_queuesmart_mp3_consolidate`(
  p_fecha_proceso DATE
)
BEGIN
  DECLARE start_date DATE;
  DECLARE v_load_date DATETIME;

  SET start_date = DATE_SUB(p_fecha_proceso, INTERVAL 3 DAY);
  SET v_load_date = DATETIME(CURRENT_TIMESTAMP(), 'America/Lima');

  -- ==========================================
  -- 1.1 Catálogo MP3 en GCS (Método Vaso de Agua)
  -- ==========================================
  CREATE OR REPLACE TEMP TABLE temp_mp3_catalog AS
  WITH base_ranked AS (
    SELECT
      fecha_audio,
      fecha_procesamiento,
      file_name,
      gcs_uri,
      gcs_path,
      campus_code,
      type_code,
      correlative,
      s3_uri,
      s3_key,
      file_size_bytes,
      sync_mode,
      ROW_NUMBER() OVER (
        PARTITION BY gcs_uri
        ORDER BY fecha_procesamiento DESC
      ) AS rn
    FROM `prd-utpbi-data-operation.raw_queuesmart.hist_queesmart_mp3_catalog`
    WHERE fecha_audio BETWEEN start_date AND p_fecha_proceso
  )
  SELECT
    fecha_audio AS process_day,
    fecha_procesamiento,
    file_name,
    gcs_uri,
    gcs_path,
    campus_code,
    type_code,
    correlative,
    s3_uri,
    s3_key,
    file_size_bytes,
    sync_mode,
    v_load_date AS load_date
  FROM base_ranked
  WHERE rn = 1;

  DELETE FROM `prd-utpbi-data-operation.raw_queuesmart.queuesmart_mp3_catalog`
  WHERE gcs_uri IN (SELECT DISTINCT gcs_uri FROM temp_mp3_catalog);

  INSERT INTO `prd-utpbi-data-operation.raw_queuesmart.queuesmart_mp3_catalog` (
    process_day,
    fecha_procesamiento,
    file_name,
    gcs_uri,
    gcs_path,
    campus_code,
    type_code,
    correlative,
    s3_uri,
    s3_key,
    file_size_bytes,
    sync_mode,
    load_date
  )
  SELECT
    process_day,
    fecha_procesamiento,
    file_name,
    gcs_uri,
    gcs_path,
    campus_code,
    type_code,
    correlative,
    s3_uri,
    s3_key,
    file_size_bytes,
    sync_mode,
    load_date
  FROM temp_mp3_catalog;

  DROP TABLE temp_mp3_catalog;

  -- ==========================================
  -- 1.2 CRM Ticketero (Método Vaso de Agua)
  -- ==========================================
  CREATE OR REPLACE TEMP TABLE temp_ticketero_crm AS
  WITH base_ranked AS (
    SELECT
      fecha_extraccion,
      fecha_procesamiento,
      apellido_paterno,
      cliente_tipo,
      cliente_estado,
      cliente_url,
      asesor_nombre,
      asesor_usuario,
      asesor_codigo,
      transferido,
      num_celular,
      enviado_sms,
      record_id,
      audio,
      audio_fecha,
      ROW_NUMBER() OVER (
        PARTITION BY record_id
        ORDER BY fecha_procesamiento DESC
      ) AS rn
    FROM `prd-utpbi-data-operation.raw_queuesmart.hist_queuesmart_ticketero_raw`
    WHERE COALESCE(audio_fecha, fecha_extraccion) BETWEEN start_date AND p_fecha_proceso
      AND record_id IS NOT NULL
  )
  SELECT
    COALESCE(audio_fecha, fecha_extraccion) AS process_day,
    fecha_extraccion,
    fecha_procesamiento,
    apellido_paterno,
    cliente_tipo,
    cliente_estado,
    cliente_url,
    asesor_nombre,
    asesor_usuario,
    asesor_codigo,
    transferido,
    num_celular,
    enviado_sms,
    record_id,
    audio,
    audio_fecha,
    v_load_date AS load_date
  FROM base_ranked
  WHERE rn = 1;

  DELETE FROM `prd-utpbi-data-operation.raw_queuesmart.queuesmart_ticketero_crm`
  WHERE record_id IN (SELECT DISTINCT record_id FROM temp_ticketero_crm);

  INSERT INTO `prd-utpbi-data-operation.raw_queuesmart.queuesmart_ticketero_crm` (
    process_day,
    fecha_extraccion,
    fecha_procesamiento,
    apellido_paterno,
    cliente_tipo,
    cliente_estado,
    cliente_url,
    asesor_nombre,
    asesor_usuario,
    asesor_codigo,
    transferido,
    num_celular,
    enviado_sms,
    record_id,
    audio,
    audio_fecha,
    load_date
  )
  SELECT
    process_day,
    fecha_extraccion,
    fecha_procesamiento,
    apellido_paterno,
    cliente_tipo,
    cliente_estado,
    cliente_url,
    asesor_nombre,
    asesor_usuario,
    asesor_codigo,
    transferido,
    num_celular,
    enviado_sms,
    record_id,
    audio,
    audio_fecha,
    load_date
  FROM temp_ticketero_crm;

  DROP TABLE temp_ticketero_crm;

  -- ==========================================
  -- 1.3 MP3 enriquecido GCS + CRM
  -- ==========================================
  CREATE OR REPLACE TEMP TABLE temp_mp3_enriched AS
  WITH catalog AS (
    SELECT *
    FROM `prd-utpbi-data-operation.raw_queuesmart.queuesmart_mp3_catalog`
    WHERE process_day BETWEEN start_date AND p_fecha_proceso
  ),
  crm AS (
    SELECT *
    FROM `prd-utpbi-data-operation.raw_queuesmart.queuesmart_ticketero_crm`
    WHERE process_day BETWEEN start_date AND p_fecha_proceso
  ),
  joined AS (
    SELECT
      COALESCE(c.process_day, r.process_day) AS process_day,
      CASE
        WHEN c.gcs_uri IS NOT NULL AND r.record_id IS NOT NULL THEN 'BOTH'
        WHEN c.gcs_uri IS NOT NULL THEN 'GCS_ONLY'
        ELSE 'CRM_ONLY'
      END AS match_status,
      c.gcs_uri,
      COALESCE(c.file_name, r.audio) AS file_name,
      COALESCE(c.file_name, r.audio) AS audio,
      r.record_id,
      c.campus_code,
      c.type_code,
      c.correlative,
      c.file_size_bytes,
      r.cliente_tipo,
      r.cliente_estado,
      r.cliente_url,
      r.asesor_nombre,
      r.asesor_usuario,
      r.asesor_codigo,
      r.num_celular,
      r.enviado_sms,
      r.transferido,
      r.apellido_paterno,
      COALESCE(c.process_day, r.audio_fecha) AS audio_fecha,
      c.fecha_procesamiento AS catalog_fecha_procesamiento,
      r.fecha_procesamiento AS crm_fecha_procesamiento,
      v_load_date AS load_date
    FROM catalog AS c
    FULL OUTER JOIN crm AS r
      ON c.file_name = r.audio
  ),
  ranked AS (
    SELECT
      *,
      ROW_NUMBER() OVER (
        PARTITION BY COALESCE(record_id, gcs_uri, audio)
        ORDER BY catalog_fecha_procesamiento DESC, crm_fecha_procesamiento DESC
      ) AS rn
    FROM joined
  )
  SELECT * EXCEPT(rn)
  FROM ranked
  WHERE rn = 1;

  DELETE FROM `prd-utpbi-data-operation.raw_queuesmart.queuesmart_mp3_enriched`
  WHERE process_day BETWEEN start_date AND p_fecha_proceso;

  INSERT INTO `prd-utpbi-data-operation.raw_queuesmart.queuesmart_mp3_enriched` (
    process_day,
    match_status,
    gcs_uri,
    file_name,
    audio,
    record_id,
    campus_code,
    type_code,
    correlative,
    file_size_bytes,
    cliente_tipo,
    cliente_estado,
    cliente_url,
    asesor_nombre,
    asesor_usuario,
    asesor_codigo,
    num_celular,
    enviado_sms,
    transferido,
    apellido_paterno,
    audio_fecha,
    catalog_fecha_procesamiento,
    crm_fecha_procesamiento,
    load_date
  )
  SELECT
    process_day,
    match_status,
    gcs_uri,
    file_name,
    audio,
    record_id,
    campus_code,
    type_code,
    correlative,
    file_size_bytes,
    cliente_tipo,
    cliente_estado,
    cliente_url,
    asesor_nombre,
    asesor_usuario,
    asesor_codigo,
    num_celular,
    enviado_sms,
    transferido,
    apellido_paterno,
    audio_fecha,
    catalog_fecha_procesamiento,
    crm_fecha_procesamiento,
    load_date
  FROM temp_mp3_enriched;

  DROP TABLE temp_mp3_enriched;

END;
