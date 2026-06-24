# Credenciales AWS — workaround temporal (env vars)

Mientras se resuelven permisos de **Secret Manager** en la SA del Cloud Run Job, las claves AWS van por **variables de entorno**.

> **No commitear claves en el repo.** Usar Cloud Run / Cloud Shell / `.env` local (gitignored).

---

## Estado actual

En `src/config/config.json`:

```json
"secrets": {
  "source": "env",
  ...
}
```

`secrets_loader.py` lee:

| Variable | Uso |
|----------|-----|
| `AWS_ACCESS_KEY_ID` | Access key AWS |
| `AWS_SECRET_ACCESS_KEY` | Secret key AWS |

Si faltan, el job falla con error de credenciales (no intenta Secret Manager).

---

## Cloud Build — activador (recomendado)

En **Cloud Build → Activador → Variables de sustitución**, agregar:

| Variable sustitución | Se inyecta en el Job como |
|----------------------|---------------------------|
| `_AWS_ACCESS_KEY_ID` | `AWS_ACCESS_KEY_ID` |
| `_AWS_SECRET_ACCESS_KEY` | `AWS_SECRET_ACCESS_KEY` |

Junto con las obligatorias del pipeline: `_PROJECT_ID`, `_JOB_NAME`, `_SERVICE_ACCOUNT`, `_BUCKET_NAME`, `_DATASET_ID`, `_AWS_S3_BUCKET`, etc.

El deploy (`cloudbuild_deploy.sh`) las pasa al Cloud Run Job en cada pipeline. **No commitear valores en el repo** — solo en el activador.

> Cuando migren a Secret Manager, quitar `_AWS_*` del activador y seguir el checklist abajo.

---

## Configurar en Cloud Run Job (manual, sin pipeline)

```bash
PROJECT_ID=dev-utpbi-data-operation
REGION=us-central1
JOB_NAME=dev-utpbi-s3-to-gcs-micro-batch

gcloud run jobs update "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --update-env-vars="AWS_ACCESS_KEY_ID=TU_ACCESS_KEY,AWS_SECRET_ACCESS_KEY=TU_SECRET_KEY"
```

O en consola: **Cloud Run → Jobs → tu job → Edit → Variables & secrets → Environment variables**.

---

## Prueba local

```bash
cd qs_s3_to_gcs/src
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export SYNC_MODE=backfill_all
python main.py
```

Opcional: copiar `.env.example` a `.env` (no se sube a git) y `source .env` antes de correr.

---

## Deploy manual (`deploy.sh`)

Exportar antes de ejecutar:

```bash
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
./deploy.sh
```

El script ya incluye esas vars en `--set-env-vars` del Job si están en el shell.

---

## Cloud Build (legacy)

Ver sección **Cloud Build — activador** arriba. Evitar poner claves en `cloudbuild.yaml` del repo.

---

## Volver a Secret Manager (TODO)

Cuando la SA `dev-utp-eduflow-sa@...` (o la de prod) tenga acceso:

### 1. IAM en el secret

```bash
gcloud secrets add-iam-policy-binding QueeSmartSecrets \
  --project=596502577187 \
  --member="serviceAccount:dev-utp-eduflow-sa@dev-utpbi-data-operation.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### 2. Verificar JSON del secret

```bash
gcloud secrets versions access latest \
  --secret=QueeSmartSecrets \
  --project=596502577187 | jq 'keys'
```

Debe incluir `aws_access_key_id` y `aws_secret_access_key`.

### 3. Cambiar config

En `src/config/config.json`:

```json
"secrets": {
  "source": "secret_manager",
  "secret_resource": "projects/596502577187/secrets/QueeSmartSecrets",
  ...
}
```

### 4. Quitar del activador y del Job

- Eliminar `_AWS_ACCESS_KEY_ID` y `_AWS_SECRET_ACCESS_KEY` del activador Cloud Build.
- Ejecutar:

```bash
gcloud run jobs update "$JOB_NAME" \
  --project="$PROJECT_ID" \
  --region="$REGION" \
  --remove-env-vars="AWS_ACCESS_KEY_ID,AWS_SECRET_ACCESS_KEY"
```

### 5. Redeploy imagen y probar

```bash
gcloud run jobs execute "$JOB_NAME" --project="$PROJECT_ID" --region="$REGION"
```

Revisar logs: no debe aparecer error de Secret Manager ni de credenciales AWS.

### 6. Rotar claves AWS (recomendado)

Si las claves estuvieron en env vars o en chat, rotarlas en IAM AWS y actualizar solo el secret (o env) según el modo activo.

---

## Checklist migración

- [ ] IAM `secretAccessor` en `QueeSmartSecrets` para la SA del job
- [ ] `secrets.source` → `secret_manager` en config.json
- [ ] Eliminar `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` del Job
- [ ] Redeploy + ejecución de prueba
- [ ] Rotar claves AWS si hubo exposición temporal
