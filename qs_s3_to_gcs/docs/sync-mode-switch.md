# Cambio de modo sync — prueba (15 días) ↔ producción (ayer)

## Modos disponibles

| `sync.mode` | Qué trae | Cuándo usar |
|-------------|----------|-------------|
| `daily_last_n_days` | Últimos **N** días (fecha en el nombre), hasta **ayer** | **Prueba actual** |
| `daily_yesterday` | Solo **ayer** (`America/Lima`) | **Producción** con scheduler |
| `backfill_all` | Todo el histórico en S3 | Carga inicial completa |

Ventana de `daily_last_n_days` (ej. N=15, hoy 13-mar):

```
2026-02-26 .. 2026-03-12   (15 días inclusive, terminando ayer)
```

---

## Ahora — prueba últimos 15 días

### Opción A: `config.json` (ya configurado)

```json
"sync": {
  "mode": "daily_last_n_days",
  "lookback_days": 15,
  "timezone": "America/Lima"
}
```

### Opción B: solo en esta ejecución (sin redeploy)

```bash
gcloud run jobs execute dev-utpbi-s3-to-gcs-micro-batch \
  --project=dev-utpbi-data-operation \
  --region=us-central1 \
  --update-env-vars=SYNC_MODE=daily_last_n_days,SYNC_LOOKBACK_DAYS=15
```

Repetir la ejecución si `copied` llega al límite de batch (`max_files` / `max_total_mb`) hasta `copied: 0`.

---

## Volver a producción — solo ayer

### 1. Cambiar config y redeploy

En `src/config/config.json`:

```json
"sync": {
  "mode": "daily_yesterday",
  "timezone": "America/Lima"
}
```

Quitar o ignorar `lookback_days` en producción.

### 2. O variable de entorno en el Job / activador

Agregar al activador Cloud Build (o quitar las de prueba):

```
SYNC_MODE=daily_yesterday
```

Y **eliminar** del Job si existían:

- `SYNC_LOOKBACK_DAYS`

```bash
gcloud run jobs update dev-utpbi-s3-to-gcs-micro-batch \
  --project=dev-utpbi-data-operation \
  --region=us-central1 \
  --update-env-vars=SYNC_MODE=daily_yesterday \
  --remove-env-vars=SYNC_LOOKBACK_DAYS
```

> Si `SYNC_MODE` viene del activador en cada deploy, basta con cambiar el activador y volver a correr el pipeline.

### 3. Activar scheduler diario

```bash
cd qs_s3_to_gcs/src
./setup-scheduler.sh
```

Cron default: `0 5 * * *` (`America/Lima`).

### 4. Verificar

```bash
gcloud run jobs execute dev-utpbi-s3-to-gcs-micro-batch \
  --project=dev-utpbi-data-operation \
  --region=us-central1
```

En logs / JSON resumen debe verse:

```json
"mode": "daily_yesterday",
"target_date": "2026-03-12"
```

(un solo día, no un rango `..`).

---

## Variables de entorno sync

| Variable | Efecto |
|----------|--------|
| `SYNC_MODE` | `daily_last_n_days` \| `daily_yesterday` \| `backfill_all` |
| `SYNC_LOOKBACK_DAYS` | N días en modo `daily_last_n_days` (default 15) |
| `SYNC_TARGET_DATE` | Un día fijo `YYYY-MM-DD` (solo con `daily_yesterday`) |

---

## Checklist vuelta a producción

- [ ] `sync.mode` = `daily_yesterday` en config o `SYNC_MODE` en activador
- [ ] Quitar `SYNC_LOOKBACK_DAYS` del Job / activador
- [ ] Redeploy pipeline (si cambió config en repo)
- [ ] Scheduler activo (`setup-scheduler.sh`)
- [ ] Ejecución de prueba: `target_date` = un solo día (ayer)
