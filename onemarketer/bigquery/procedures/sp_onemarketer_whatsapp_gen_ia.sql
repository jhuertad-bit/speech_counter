-- =============================================================================
-- Stored Procedure: Gen IA sobre MP3 WhatsApp/OneMarketer
-- Patrón equivalente a Genesys (external table + AI.GENERATE_TABLE + hist)
--
-- Desplegar (ejemplo dev):
--   bq query --use_legacy_sql=false < procedures/sp_onemarketer_whatsapp_gen_ia.sql
--
-- Ejecutar:
--   CALL `dev-utpbi-data-operation.adf_speech_analytics.sp_onemarketer_whatsapp_gen_ia`(DATE '2026-06-09');
-- =============================================================================

CREATE OR REPLACE PROCEDURE `${PROJECT_ID}.${DATASET_ANALYTICS}.sp_onemarketer_whatsapp_gen_ia`(
  v_fecha_proceso DATE
)
BEGIN
  DECLARE v_fecha_proceso_str STRING;
  DECLARE external_table STRING;
  DECLARE conexion STRING;
  DECLARE v_uris STRING;
  DECLARE v_sql STRING;
  DECLARE min_duration_seconds FLOAT64 DEFAULT 0.0;

  SET v_fecha_proceso_str = FORMAT_DATE('%Y-%m-%d', v_fecha_proceso);
  SET external_table = '${EXTERNAL_TABLE_TMP}';
  SET conexion = '${BQ_CONNECTION}';

  -- ---------------------------------------------------------------------------
  -- 1. Armar URIs desde reporte_whatsapp_mp3 (MP3 OK del día)
  -- ---------------------------------------------------------------------------
  SET v_uris = (
    WITH base AS (
      SELECT mp3.gcs_uri AS uri
      FROM `${PROJECT_ID}.${DATASET_RAW}.reporte_whatsapp_mp3` AS mp3
      WHERE mp3.fecha_evento = v_fecha_proceso
        AND mp3.conversion_status IN ('OK', 'SKIPPED_EXISTS', 'SKIPPED_ALREADY_MP3')
        AND mp3.gcs_uri IS NOT NULL
        AND IFNULL(mp3.duration_seconds, 0) >= min_duration_seconds
    )
    SELECT CONCAT(
      '[',
      STRING_AGG(CONCAT('"', uri, '"'), ', '),
      ']'
    )
    FROM base
  );

  IF v_uris IS NULL OR v_uris = '[]' THEN
    SELECT FORMAT('Sin URIs MP3 para fecha %s — SP finaliza sin procesar.', v_fecha_proceso_str);
    RETURN;
  END IF;

  -- ---------------------------------------------------------------------------
  -- 2. External table con las URIs (conexión GCS)
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
  -- 3. Metadata MP3 + chat + objeto audio del external table
  -- ---------------------------------------------------------------------------
  EXECUTE IMMEDIATE FORMAT("""
    CREATE OR REPLACE TEMP TABLE tmp_onemarketer_whatsapp_audios AS
    SELECT
      mp3.fecha_evento AS process_date,
      mp3.gcs_uri,
      mp3.idcase,
      mp3.idmessage,
      mp3.waid,
      mp3.duration_seconds,
      mp3.file_name,
      chats.text AS chat_text,
      chats.origin AS chat_origin,
      chats.`user` AS chat_user,
      ext.ref AS audio,
      CONCAT(
        'Analiza el audio de WhatsApp adjunto a esta conversación OneMarketer. ',
        'Devuelve UN objeto JSON con las claves: ',
        'transcripcion (texto literal del audio en español si aplica), ',
        'resumen (máx 3 oraciones), intencion (consulta, reclamo, interés académico, otro), ',
        'idioma, tono (neutral, positivo, negativo, urgente), ',
        'entidades (nombres, carreras, campus mencionados; string), ',
        'observaciones (string). ',
        'Contexto del hilo (puede estar vacío): ',
        IFNULL(chats.text, '(sin texto en reporte_chats)')
      ) AS prompt
    FROM `${PROJECT_ID}.${DATASET_RAW}.reporte_whatsapp_mp3` AS mp3
    INNER JOIN %s AS ext
      ON ext.uri = mp3.gcs_uri
    LEFT JOIN `${PROJECT_ID}.${DATASET_RAW}.reporte_chats` AS chats
      ON chats.fecha_evento = mp3.fecha_evento
     AND chats.idcase = mp3.idcase
     AND chats.idmessage = mp3.idmessage
    WHERE mp3.fecha_evento = DATE('%s')
      AND mp3.conversion_status IN ('OK', 'SKIPPED_EXISTS', 'SKIPPED_ALREADY_MP3')
      AND IFNULL(mp3.duration_seconds, 0) >= %f
  """, external_table, v_fecha_proceso_str, min_duration_seconds);

  -- ---------------------------------------------------------------------------
  -- 4. Gen IA (Gemini) — un batch; ampliar con INSERTs por segmento si negocio lo pide
  -- ---------------------------------------------------------------------------
  CREATE OR REPLACE TEMP TABLE tmp_onemarketer_whatsapp_gen_ia_results AS
  SELECT ia.*
  FROM AI.GENERATE_TABLE(
    MODEL ${GEMINI_MODEL},
    (
      SELECT
        STRUCT(
          prompt AS instruction,
          OBJ.GET_ACCESS_URL(audio, 'r') AS audio_url
        ) AS prompt,
        * EXCEPT(prompt, audio)
      FROM tmp_onemarketer_whatsapp_audios
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
  DELETE FROM `${PROJECT_ID}.${DATASET_ANALYTICS}.hist_onemarketer_whatsapp_gen_ia_process_data_raw`
  WHERE process_date = v_fecha_proceso;

  INSERT INTO `${PROJECT_ID}.${DATASET_ANALYTICS}.hist_onemarketer_whatsapp_gen_ia_process_data_raw`
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
    FROM tmp_onemarketer_whatsapp_gen_ia_results AS ia
  ),
  cte_parsed AS (
    SELECT
      process_date,
      gcs_uri,
      idcase,
      idmessage,
      waid,
      duration_seconds,
      chat_text,
      chat_origin,
      chat_user,
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
  DELETE FROM `${PROJECT_ID}.${DATASET_ANALYTICS}.hist_onemarketer_whatsapp_gen_ia_process_data_prd`
  WHERE process_date = v_fecha_proceso;

  INSERT INTO `${PROJECT_ID}.${DATASET_ANALYTICS}.hist_onemarketer_whatsapp_gen_ia_process_data_prd`
  SELECT
    process_date,
    gcs_uri,
    idcase,
    idmessage,
    waid,
    duration_seconds,
    transcripcion,
    resumen,
    intencion,
    idioma,
    tono,
    entidades,
    observaciones,
    chat_text,
    chat_origin,
    load_date
  FROM `${PROJECT_ID}.${DATASET_ANALYTICS}.hist_onemarketer_whatsapp_gen_ia_process_data_raw`
  WHERE process_date = v_fecha_proceso;

END;
