# Estado de Avance del Proyecto  
## Plataforma de audio, transcripción y evaluación IA  

**Preparado por** ZAT Consultora de Datos — Noviembre 2026  
**Proyecto** UTP — Noviembre 2026  
**Periodo:** 1 al 25 de noviembre de 2026  
**Frentes:** Canal Counter | Canal escrito | Canal hablado Genesys / Speech Analytics 125 | Prospección Promotores | Prospección Mentores | Operación y resiliencia  
**Responsable:** Diego Armando Tovar Espinoza  

**Estado:** Speech Analytics 125 (extracción Paul) en pipeline diario con flatten a tabla BI; QueueSmart STT partido en lotes con checkpoint por tiempo; OneMarketer endurecido (timezone Lima, resumen final, retry medios); inventario de colas del mail Speech y material de nuevas pautas TLMK recibido (implementación pendiente).  

**Resultado del mes.** Noviembre concentró la entrega de **Speech Analytics 125** (init → batch Gemini → parse → flatten → vista CRM), la **resiliencia operativa** de pipelines largos (checkpoint SA-125 y partición STT QueueSmart ante `backendError`), y el cierre de huecos de **canal escrito / atenciones** (timezone GMT-05, backfill reporteAtenciones, resumen final por asesor). En Genesys se respondió el pedido de colas Speech (catálogo UUID + altas en SP Admisión). Quedó documentado el backlog de **nuevas pautas de calidad TLMK** (9 prompts + Excel) sin implementación aún.

**Fuentes:** commits noviembre en `monorep-utp-funcionts-runs` y `speech_counter` (autor Diego Tovar), más operación documentada en workflows y SQL de reanudación.

---

## 1. Resumen ejecutivo

En **canal hablado**, el hito del mes no fue una nueva calibración de pauta de calidad legacy, sino el producto **Speech Analytics 125**: extracción estructurada desde transcripción Markov (prompt Paul), orquestado por Cloud Workflows con reanudación por offset, tipificación desde CRM Genesys, y capa **flat** para consumo BI (`hist_speech_analytics_125_flat_prd` + vista CRM).

En **Canal Counter**, el STT Chirp dejó de depender de un único `CALL` monolítico vulnerable a `backendError`: se separó en **init / batch / prd** y el workflow diario hace loop con checkpoint por tiempo (mismo patrón que SA-125). Se sumó el SP de **resumen final por asesor** al pipeline diario.

En **canal escrito**, OneMarketer avanzó en corrección de **fecha_evento / Lima (GMT-05)**, job de backfill de atenciones, SP de resumen final escrito, y endurecimiento ETL (retry descargachats 5×30s + soft-fail de medios ante 502 para no tumbar chats).

En **Prospección**, Mentores se operó con backfill multi-fecha (script Cloud Shell) y se sostuvo el flujo diario. Promotores se mantuvo operativo.

**Principales avances del mes**

- Pipeline diario **genesys-sa125-daily**: init, batch, parse, flatten, checkpoint por tiempo (`skip_init` / `start_offset`).
- Tabla y SP **flatten** 125 + funciones de limpieza (flags SI/NO/NA, listas JSON, texto).
- **QueueSmart** STT: `sp_queuesmart_mp3_gen_ia_{init,batch,prd}` + workflow con reanudación; SQL de resume por fecha.
- Altas de **colas Admisión** (NACIONAL, MEDICINA, EVENTOS*) desde `queues_raw` en `end_processing_admision_v2`.
- Catálogo / diagnóstico de colas del mail Speech (Voz ya en eval; Admisión/Escritos diferenciados).
- OneMarketer: timezone Lima, resumen final, retries 502, soft-fail medios.
- `qsmart_transcribe`: escritura BQ por DML (evitar streaming buffer), truncado JSON grande, timeouts STT.
- Material **prompts_tlmk** + `PENDIENTES.md` (viabilidad / alcance v1 documentado).

### Estado general por frente

| Frente | Estado al cierre de noviembre | Observación |
|---|---|---|
| Canal Counter — pauta | v9 VIGENTE | Sin nueva iteración de pauta de calidad. |
| Canal Counter — Gen IA / STT | RESILIENTE | STT por lotes + checkpoint; resumen final en pipeline diario. |
| Canal Counter — VASO / Whisper | OPERATIVO | Se mantiene lo de setiembre/octubre; docs vaso en monorepo. |
| Canal escrito | OPERATIVO + HARDENING | Timezone Lima, resumen final, ETL más tolerante a 502 medios. |
| Canal hablado Genesys (pauta calidad) | OPERATIVO | Calibración previa vigente; nuevas pautas TLMK en backlog. |
| Speech Analytics 125 | ENTREGADO EN PIPELINE | Extracción + flat BI; backfill de fechas en curso / reanudable. |
| Prospección Promotores | OPERATIVO | Sin cambio de alcance material en commits del mes. |
| Prospección Mentores | INGESTA + BACKFILL | Script backfill 8-oct→9-nov; evaluación IA sigue fuera. |
| Pautas calidad TLMK (nuevo mail) | MATERIAL RECIBIDO | 9 DOCX + Excel; implementación y calibración pendientes. |

---

## 2. Frente Canal Counter (QueueSmart)

### 2.1 STT y resiliencia del pipeline diario

Tras fallos `backendError` en el `CALL` monolítico `sp_queuesmart_mp3_gen_ia` (p. ej. process_date 2026-11-05 / 2026-11-17), se partió el STT en:

1. `sp_queuesmart_mp3_gen_ia_init` — limpia hist (opcional) y materializa candidatos en staging.  
2. `sp_queuesmart_mp3_gen_ia_batch` — un lote ML.TRANSCRIBE → raw.  
3. `sp_queuesmart_mp3_gen_ia_prd` — timed transcript + merge a PRD.  

El workflow `queuesmart-daily-pipeline` orquesta el loop con `start_offset`, `skip_init`, `skip_ingest` y checkpoint por tiempo (spawn de continuación), alineado a la regla de workflows del monorepo.

- Reanudación documentada en `queuesmart/bigquery/sqls/resume_stt_offset_dia.sql`.  
- Orquestador monolítico conservado para CALL manual (`sp_queuesmart_mp3_gen_ia_A2`).

### 2.2 Resumen final y capa analítica

- SP `sp_queuesmart_counter_resumen_final` y tabla asociada integrados al deploy y al workflow diario (post Gemini).  
- Pauta Counter v9 y vistas CRM de octubre se mantienen; este mes no las reabrió.

### 2.3 Transcribe (repo speech_counter)

- `qsmart_transcribe` / `bq_writer`: INSERT vía DML (evita límites del streaming buffer), tipado `rowid`, truncado de JSON grandes hacia BQ, timeouts STT ajustados.

---

## 3. Frente Canal escrito (OneMarketer)

### 3.1 Calidad de fecha y atenciones

- Corrección de **timezone America/Lima (GMT-05)** en API / `fecha_evento` (probe + monorepo `onemarketer-api`).  
- Job / scripts de **backfill reporteAtenciones** y diagnósticos de lead vacío.  
- Ajustes de esquema `reporteAtenciones` y despliegue Cloud Build.

### 3.2 Gen IA y resumen

- Refactor de SPs WhatsApp / caso conversación; SP **`sp_onemarketer_escrito_resumen_final`** en el pipeline diario.  
- Vistas CRM lead / conversaciones mantenidas y optimizadas en el refactor de noviembre.

### 3.3 ETL y operación

- Retry API **descargachats**: 5 intentos, 30 s entre reintentos (502 Proxy Error del 19-nov).  
- **Soft-fail de medios:** si falla descargachats tras retries, no se marca fallido el día si `reporteChats` ya cargó (el workflow ya no corta por medios solos).  
- Pendiente operativo: redeploy CF + reproceso de fechas afectadas (p. ej. 2026-11-19); alertas email bloqueadas por falta de rol Monitoring.

---

## 4. Frente Canal hablado — Genesys y Speech Analytics 125

### 4.1 Speech Analytics 125 (extracción Paul)

Entrega principal del mes:

- SPs: `init`, `batch`, `parse`, `flatten`, `run_day`.  
- Tablas raw/prd + **`hist_speech_analytics_125_flat_prd`**.  
- Funciones: normalización de bloques, postprocess, flat (clean text, flags, json list).  
- Vista `v_speech_analytics_125_crm` (COALESCE conversation_id, tipificación desde CRM `conclusion_nombres` / tipificacion).  
- Workflow **genesys-sa125-daily** con checkpoint por tiempo y continuación `skip_init` + `start_offset` (ej. 3520/4540 sin borrar RAW).  
- Documentación de persistencia, validación 100, gap diccionario vs Genesys, prompts load.

### 4.2 Colas Speech (mail operativo)

- Inventario previo a joins; lookup UUID en `raw_genesys.queues_raw`.  
- Catálogo vivo `catalogo_colas_mail_encontradas.sql`.  
- Voz listada: CRM ≈ prompt ≈ eval (funnel 30d).  
- Admisión: UUID de MEDICINA / EVENTOS* / NACIONAL agregados al filtro `cola_id IN` de `sp_utpbi_genesys_end_processing_admision_v2` (volumen en raw pendiente de descarga donde aplique).  
- Escritos: fuera de ese SP (otro pipeline).

### 4.3 Pauta de calidad Genesys (legacy)

- Sin nueva calibración de prompts `utp_pront_instruccions` en el mes.  
- **Nuevo requerimiento:** implementar prompts de pautas TLMK (y Admisión #3). Material en `prompts_tlmk/`; pendientes en `PENDIENTES.md` (mapa tipif, schema EXP/COM/CUM/TRA, motor de pesos/críticos, calibración vs Calidad).

---

## 5. Frente Prospección

### 5.1 Promotores

- Operación diaria sostenida (copia, catálogo, Whisper, evaluaciones). Sin hito de alcance nuevo en commits significativos de noviembre.

### 5.2 Mentores

- Pipeline diario `prd-utpbi-mentores-gcs-copy` operativo.  
- Script `mentores_gcs_copy/scripts/backfill_fechas_cloudshell.sh` para reprocesar rangos (p. ej. 2026-10-08 → 2026-11-09), con wait por ejecución.  
- Evaluación con IA sigue fuera de alcance de este flujo.

---

## 6. Operación, documentación y continuidad

- Guías Cloud Shell / operación Speech Analytics actualizadas en monorepo.  
- Regla de checkpoint por tiempo para workflows con loops largos (referencia SA-125).  
- Continuidad: Paul Ramírez opera pipelines; noviembre aportó patrones de **reanudación** (SA-125, QueueSmart STT) para no depender de re-ejecuciones desde cero.

---

## 7. Pendientes / siguientes pasos (cierre noviembre)

1. Completar backfills SA-125 (fechas octubre–noviembre según plan) y validar flat BI.  
2. Redeploy CF OneMarketer (retry + soft-fail) y reprocesar 2026-11-19 (medios).  
3. Alertas email de workflows (pendiente rol Monitoring).  
4. Partir STT OneMarketer con el mismo patrón init/batch/checkpoint si aparecen `backendError`.  
5. Kickoff **pautas TLMK v1 (solo Voz)** según `prompts_tlmk/PENDIENTES.md` + muestra de calibración Calidad.  
6. Admisión del mail de pautas (#3): material de prompts aún no recibido en la carpeta TLMK.  
7. Confirmar volumen raw de colas Admisión nuevas tras descarga Genesys.

---

## 8. Referencia de commits (noviembre 2026)

### monorep-utp-funcionts-runs (Diego Tovar)

| Fecha | Tema |
|---|---|
| 2026-11-17 | OneMarketer SPs/vistas/resumen; SA-125 init/batch/parse; QueueSmart resumen; vaso docs |
| 2026-11-23 | SA-125 flatten + FNs + tipificación; OM API/timezone en monorepo; qsmart_transcribe timeouts |
| 2026-11-25 | Flatten en workflow SA-125; colas Admisión UUID; QueueSmart STT init/batch/prd + checkpoint; OM retry/soft-fail; prompts_tlmk + PENDIENTES; mentores backfill script |

### speech_counter (Diego Tovar)

| Fecha | Tema |
|---|---|
| 2026-11-10 | VASO / Mentores docs; qsmart_transcribe deploy; backfill atenciones |
| 2026-11-11–12 | onemarketer-api + job backfill atenciones / esquema |
| 2026-11-17–18 | bq_writer DML, tipado, truncado JSON, timeouts STT |
| 2026-11-23 | Timezone Lima / fecha_evento OneMarketer API |

---

*Documento alineado al formato del informe de octubre. Periodo cerrado al 25/11/2026 (día de emisión).*
