-- =============================================================================
-- SP: Gen IA MP3 QueeSmart — PRODUCCIÓN
--
-- Proyecto:  prd-utpbi-data-operation
-- Fuente:    raw_queuesmart.hist_queesmart_mp3_catalog (us-central1)
-- SP + hist: adf_speech_analytics (US)
-- Modelo:    adf_speech_analytics.gemini-2-5-flash
-- Conexión:  US.utp_gen_ia_process (bucket GCS QueeSmart)
--
-- Patrón Genesys / OneMarketer: external table + AI.GENERATE_TABLE + hist
--
-- Ejecutar (diario, después de qs_s3_to_gcs):
--   CALL `prd-utpbi-data-operation.adf_speech_analytics.sp_queuesmart_mp3_gen_ia`(
--     DATE_SUB(CURRENT_DATE('America/Lima'), INTERVAL 1 DAY)
--   );
-- =============================================================================

CREATE OR REPLACE PROCEDURE `prd-utpbi-data-operation.adf_speech_analytics.sp_queuesmart_mp3_gen_ia`(
  v_fecha_proceso DATE
)
BEGIN
  DECLARE v_fecha_proceso_str STRING;
  DECLARE external_table STRING;
  DECLARE conexion STRING;
  DECLARE v_uris STRING;
  DECLARE v_sql STRING;

  SET v_fecha_proceso_str = FORMAT_DATE('%Y-%m-%d', v_fecha_proceso);
  SET external_table = '`prd-utpbi-data-operation.adf_speech_analytics.tmp_utp_external_table_queuesmart_mp3`';
  SET conexion = '`prd-utpbi-data-operation.US.utp_gen_ia_process`';

  -- ---------------------------------------------------------------------------
  -- 1. URIs desde hist_queesmart_mp3_catalog (dedup por gcs_uri)
  -- ---------------------------------------------------------------------------
  SET v_uris = (
    WITH base_ranked AS (
      SELECT
        gcs_uri,
        ROW_NUMBER() OVER (
          PARTITION BY gcs_uri
          ORDER BY fecha_procesamiento DESC
        ) AS rn
      FROM `prd-utpbi-data-operation.raw_queuesmart.hist_queesmart_mp3_catalog`
      WHERE fecha_audio = v_fecha_proceso
        AND gcs_uri IS NOT NULL
    )
    SELECT CONCAT(
      '[',
      STRING_AGG(CONCAT('"', gcs_uri, '"'), ', '),
      ']'
    )
    FROM base_ranked
    WHERE rn = 1
  );

  IF v_uris IS NULL OR v_uris = '[]' THEN
    SELECT FORMAT(
      'Sin URIs en hist_queesmart_mp3_catalog para fecha %s.',
      v_fecha_proceso_str
    );
    RETURN;
  END IF;

  -- ---------------------------------------------------------------------------
  -- 2. External table (conexión GCS)
  -- ---------------------------------------------------------------------------
  SET v_sql = FORMAT("""
    CREATE OR REPLACE EXTERNAL TABLE %s
    WITH CONNECTION %s
    OPTIONS (
      object_metadata = 'SIMPLE',
      uris = %s,
      max_staleness = INTERVAL 30 MINUTE,
      metadata_cache_mode = AUTOMATIC
    )
  """, external_table, conexion, v_uris);
  EXECUTE IMMEDIATE v_sql;

  -- ---------------------------------------------------------------------------
  -- 3. Metadata catálogo + objeto audio
  -- ---------------------------------------------------------------------------
  EXECUTE IMMEDIATE FORMAT("""
    CREATE OR REPLACE TEMP TABLE tmp_queuesmart_mp3_audios AS
    WITH catalog AS (
      SELECT *
      FROM (
        SELECT
          c.*,
          ROW_NUMBER() OVER (
            PARTITION BY c.gcs_uri
            ORDER BY c.fecha_procesamiento DESC
          ) AS rn
        FROM `prd-utpbi-data-operation.raw_queuesmart.hist_queesmart_mp3_catalog` AS c
        WHERE c.fecha_audio = DATE('%s')
          AND c.gcs_uri IS NOT NULL
      )
      WHERE rn = 1
    )
    SELECT
      cat.fecha_audio AS process_date,
      cat.gcs_uri,
      cat.file_name,
      cat.gcs_path,
      cat.campus_code,
      cat.type_code,
      cat.correlative,
      cat.file_size_bytes,
      cat.sync_mode,
      cat.s3_uri,
      ext.ref AS audio_obj,
      CONCAT(
        'Analiza el audio de atención QueeSmart UTP (grabación en campus). ',
        'Devuelve UN objeto JSON con las claves: ',
        'transcripcion (texto literal del audio en español si aplica), ',
        'resumen (máx 3 oraciones), ',
        'intencion (consulta admisión, información carrera, trámite, reclamo, seguimiento, otro), ',
        'idioma, tono (neutral, positivo, negativo, urgente), ',
        'entidades (carreras, campus, nombres mencionados; string), ',
        'observaciones (string). ',
        'Metadatos del archivo — ',
        'archivo: ', IFNULL(cat.file_name, 'N/D'), ', ',
        'campus_code: ', IFNULL(cat.campus_code, 'N/D'), ', ',
        'type_code: ', IFNULL(cat.type_code, 'N/D'), ', ',
        'correlativo: ', IFNULL(cat.correlative, 'N/D')
      ) AS prompt
    FROM catalog AS cat
    INNER JOIN %s AS ext
      ON ext.uri = cat.gcs_uri
  """, v_fecha_proceso_str, external_table);

  -- ---------------------------------------------------------------------------
  -- 4. Gen IA (Gemini)
  -- ---------------------------------------------------------------------------
  CREATE OR REPLACE TEMP TABLE tmp_queuesmart_mp3_gen_ia_results AS
  SELECT ia.*
  FROM AI.GENERATE_TABLE(
    MODEL `prd-utpbi-data-operation.adf_speech_analytics.gemini-2-5-flash`,
    (
      SELECT
        STRUCT(
          prompt AS instruction,
          OBJ.GET_ACCESS_URL(audio_obj, 'r') AS audio_url
        ) AS prompt,
        * EXCEPT(prompt, audio_obj)
      FROM tmp_queuesmart_mp3_audios
    ),
    STRUCT(
      'ml_generate_text_llm_result STRING' AS output_schema,
      32768 AS max_output_tokens,
      0 AS temperature
    )
  ) AS ia;

  -- ---------------------------------------------------------------------------
  -- 5. Parseo JSON → hist RAW
  -- ---------------------------------------------------------------------------
  DELETE FROM `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_raw`
  WHERE process_date = v_fecha_proceso;

  INSERT INTO `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_raw`
  WITH cte_cleaned_json AS (
    SELECT
      ia.*,
      CONCAT(
        '[',
        REGEXP_EXTRACT(
          REGEXP_REPLACE(ml_generate_text_llm_result, r'`', '"'),
          r'(?s)\{.*\}'
        ),
        ']'
      ) AS json_text
    FROM tmp_queuesmart_mp3_gen_ia_results AS ia
  ),
  cte_parsed AS (
    SELECT
      process_date,
      gcs_uri,
      file_name,
      gcs_path,
      campus_code,
      type_code,
      correlative,
      file_size_bytes,
      sync_mode,
      s3_uri,
      json_text,
      full_response,
      status,
      JSON_VALUE(json_text, '$[0].transcripcion') AS transcripcion,
      JSON_VALUE(json_text, '$[0].resumen') AS resumen,
      JSON_VALUE(json_text, '$[0].intencion') AS intencion,
      JSON_VALUE(json_text, '$[0].idioma') AS idioma,
      JSON_VALUE(json_text, '$[0].tono') AS tono,
      JSON_VALUE(json_text, '$[0].entidades') AS entidades,
      JSON_VALUE(json_text, '$[0].observaciones') AS observaciones,
      DATETIME(CURRENT_TIMESTAMP(), 'America/Lima') AS load_date
    FROM cte_cleaned_json
  )
  SELECT * FROM cte_parsed;

  -- ---------------------------------------------------------------------------
  -- 6. Capa PRD (consumo)
  -- ---------------------------------------------------------------------------
  DELETE FROM `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_prd`
  WHERE process_date = v_fecha_proceso;

  INSERT INTO `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_prd`
  SELECT
    process_date,
    gcs_uri,
    file_name,
    campus_code,
    type_code,
    correlative,
    file_size_bytes,
    transcripcion,
    resumen,
    intencion,
    idioma,
    tono,
    entidades,
    observaciones,
    load_date
  FROM `prd-utpbi-data-operation.adf_speech_analytics.hist_queuesmart_mp3_gen_ia_process_data_raw`
  WHERE process_date = v_fecha_proceso;

END;
