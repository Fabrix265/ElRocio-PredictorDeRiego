# Backend – Sistema de Plan de Riego (Grupo El Rocío)

API FastAPI + SQLAlchemy 2 (psycopg 3) + Alembic sobre PostgreSQL (Supabase en producción).
Especificación: [`docs/propuesta_mvp.md`](../docs/propuesta_mvp.md).

## Instalación (Windows, Python 3.11.9)

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # incluye ../ml/requirements.txt
.venv/Scripts/python -m pip install -e ../ml                   # paquete riego_ml (solo empaquetado)
```

`requirements.txt` empieza con `-r ../ml/requirements.txt`: el modelo guardado se carga con las
mismas versiones con las que se entrenó. Todas las versiones están fijas.

## Configuración

Copia `.env.example` a `.env` y completa los valores (cada variable está comentada). `.env` no se
versiona. Las variables del entorno del proceso tienen prioridad sobre `.env`.

- `DATABASE_URL`: la usa la aplicación, con el rol `riego_app`. En Supabase, el pooler en modo
  transacción (puerto 6543): el backend usa entonces `NullPool` y desactiva los *prepared
  statements* automáticamente (`DB_POOL=auto`). Todas las tablas llevan el esquema `riego`
  explícito, así que no depende de `search_path`.
- `DATABASE_URL_MIGRACIONES`: rol dueño y conexión directa (5432), para Alembic y la CLI.

## Base de datos

### PostgreSQL local (desarrollo)

```bash
PSQL="/c/Program Files/PostgreSQL/18/bin/psql.exe"
"$PSQL" -h localhost -U postgres -c "CREATE DATABASE riego_dev ENCODING 'UTF8' TEMPLATE template0"
```

En `.env`: `DATABASE_URL_MIGRACIONES=postgresql+psycopg://postgres@localhost:5432/riego_dev` y
`DATABASE_URL=postgresql+psycopg://riego_app:<RIEGO_APP_PASSWORD>@localhost:5432/riego_dev`.

### Migraciones y rol de la aplicación

```bash
.venv/Scripts/python -m alembic upgrade head          # esquema riego + datos semilla
.venv/Scripts/python -m app.cli configurar-rol-app    # LOGIN + contraseña de riego_app (RIEGO_APP_PASSWORD)
.venv/Scripts/python -m app.cli verificar-seguridad-bd
```

- `0001_esquema_inicial`: las 32 tablas, enums, índices, triggers de inmutabilidad, rol
  `riego_app` (NOLOGIN al crearse), RLS en todas las tablas (también `alembic_version`) con una
  sola política para `riego_app`, y `REVOKE` para `PUBLIC`, `anon` y `authenticated`.
- `0002_datos_semilla`: AVO PERÚ S.A.C. y Talsa, fundo ENSUEÑO 1, módulo EN01-MOD5, turnos
  TE01–TE05, 22 lotes y los motivos de corrección. Idempotente.
- `alembic downgrade base` deja el esquema vacío (conserva `riego.alembic_version` y el rol).
- `configurar-rol-app` cifra la contraseña (SCRAM-SHA-256) en el cliente antes del `ALTER ROLE`.
- `verificar-seguridad-bd` termina con código 1 si alguna tabla quedó sin RLS, con políticas para
  otros roles, con privilegios para `PUBLIC`/`anon`/`authenticated`, si `riego_app` tiene
  privilegios de más o falta algún trigger.

### Supabase

1. `DATABASE_URL_MIGRACIONES` = conexión directa `db.<ref>.supabase.co:5432` con `postgres`.
2. `alembic upgrade head`, luego `configurar-rol-app` y `verificar-seguridad-bd`.
3. `DATABASE_URL` = pooler 6543 con el usuario `riego_app.<ref>` y la contraseña definida.

La Data API de Supabase solo publica `public`; el esquema `riego` queda fuera y, además, sin
privilegios ni políticas para `anon`/`authenticated`.

## Ejecución

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload
```

- `GET /api/v1/health` → `{status, app, entorno, bd, modelo}` (503 si la BD no responde).
- Documentación interactiva en `http://localhost:8000/docs` (deshabilitada en producción).

## Pruebas

```bash
.venv/Scripts/python -m pytest -q
```

Usan la base `riego_test` (`TEST_DATABASE_URL`; se crea y migra sola). En un servidor local, el
fixture crea los roles `anon` y `authenticated` (NOLOGIN) para comprobar que no reciben
privilegios. Cada test corre en una transacción que se deshace; las sesiones de la app usan
`SET LOCAL ROLE riego_app`, así que se prueban los mismos privilegios y RLS que en producción.
