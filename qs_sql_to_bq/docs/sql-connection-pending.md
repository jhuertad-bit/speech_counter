# Conexión SQL Server — pendiente de datos

El origen es **SQL Server on-prem** (no Azure). Hasta recibir host, base y tabla, el proyecto queda listo con placeholders.

## Variables del activador Cloud Build

| Sustitución | Env en el Job | Descripción |
|-------------|---------------|-------------|
| `_SQL_SERVER_HOST` | `SQL_SERVER_HOST` | IP o hostname del servidor |
| `_SQL_SERVER_PORT` | `SQL_SERVER_PORT` | Puerto (default `1433`) |
| `_SQL_SERVER_DATABASE` | `SQL_SERVER_DATABASE` | Base de datos |
| `_SQL_SERVER_SCHEMA` | `SQL_SERVER_SCHEMA` | Esquema (default `dbo`) |
| `_SQL_SOURCE_TABLE` | `SQL_SOURCE_TABLE` | Nombre de tabla origen |
| `_SQL_SERVER_USER` | `SQL_SERVER_USER` | Usuario SQL |
| `_SQL_SERVER_PASSWORD` | `SQL_SERVER_PASSWORD` | Contraseña |
| `_SQL_CUSTOM_QUERY` | `SQL_CUSTOM_QUERY` | (Opcional) Query completa; reemplaza SELECT automático |

## Cuando tengan los datos

1. Completar activador con las variables arriba.
2. Verificar `column_map` en `src/config/config.json` si los nombres de columna difieren.
3. Red firewall: el Cloud Run Job necesita salida TCP al puerto SQL desde VPC o IP pública permitida.
4. Ejecutar el job y revisar `inserted` en el JSON de salida.

## Query automática (sin SQL_CUSTOM_QUERY)

```sql
SELECT [doPaterno], [ClienteTipo], ... , [Audio]
FROM [dbo].[NOMBRE_TABLA]
```

El filtro por fecha (ayer / N días) se aplica en Python sobre la columna `Audio`  
(ej. `095AG24-20260318-130213.mp3` → fecha `2026-03-18`).

## Alternativa: filtrar en SQL

Cuando conozcan la tabla, pueden pasar `_SQL_CUSTOM_QUERY`:

```sql
SELECT doPaterno, ClienteTipo, ClienteEstado, ClienteURL,
       AsesorNombre, AsesorUsuario, AsesorCodigo, Transferido,
       NumCelular, EnviadoSMS, RecordID, Audio
FROM dbo.MiTabla
WHERE Audio LIKE '%-20260323-%'
```

## Checklist entrega infra

- [ ] Host / puerto SQL Server
- [ ] Database + tabla (o vista)
- [ ] Usuario con SELECT
- [ ] Regla firewall hacia Cloud Run / NAT
- [ ] Confirmar nombres exactos de columnas vs `column_map`
