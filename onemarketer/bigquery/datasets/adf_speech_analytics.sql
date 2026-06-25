-- Dataset analytics Gen IA (misma región que conexión utp_gen_ia_process y modelo Gemini).
-- Ejecutar con: bq query --use_legacy_sql=false --location=US
--
-- Si Genesys ya creó adf_speech_analytics en prd, omitir este script.

CREATE SCHEMA IF NOT EXISTS `${PROJECT_ID}.${DATASET_ANALYTICS}`
OPTIONS (
  location = 'US',
  description = 'Speech analytics / Gen IA (Genesys, OneMarketer WhatsApp MP3)'
);
