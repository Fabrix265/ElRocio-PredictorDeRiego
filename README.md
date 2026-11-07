# Sistema de Plan de Riego · Grupo El Rocío

Aplicación web de AvoPeru y Talsa para el plan de riego diario del fundo ENSUEÑO 1 (módulo
EN01-MOD5, turnos TE01–TE05). Un modelo entrenado con el historial de riego, clima (WeatherLink)
y sensores de suelo y planta (Phytech) propone cada día el número de ciclos, los m³/ha, la duración
y el horario por turno; el encargado lo revisa y lo publica, y el programador lo confirma en campo.

Especificación completa: [`docs/propuesta_mvp.md`](docs/propuesta_mvp.md).
Guía para quienes usan el sistema: [`docs/guia_usuario.md`](docs/guia_usuario.md).

## Arquitectura

```text
Navegador ──► Frontend React (Vite)          ──/api/v1──► API FastAPI (1 worker)  ──► PostgreSQL / Supabase
              frontend/  :5173 en desarrollo               backend/app  :8000          esquema `riego`
              (proxy de Vite: /api → :8000)                 │                           (RLS, rol riego_app)
                                                            └── riego_ml (ml/src) para las predicciones (fase 3)
                                              Proceso de tareas (python -m app.jobs): cola de correos,
                                              mantenimiento y, desde la fase 2, la ingesta diaria
```

| Pieza | Carpeta | Tecnología | Detalle |
|---|---|---|---|
| Frontend | `frontend/` | React 19, TypeScript estricto, Vite 8, Tailwind 4, TanStack Query/Table | [frontend/README.md](frontend/README.md) |
| API | `backend/app/` | FastAPI, SQLAlchemy 2, psycopg 3, Alembic, Pydantic v2 | [backend/README.md](backend/README.md) |
| Tareas programadas | `backend/app/jobs/` | APScheduler (proceso aparte o dentro de la API en desarrollo) | [backend/README.md](backend/README.md#correos-y-tareas-programadas) |
| Base de datos | `backend/alembic/` | PostgreSQL 15+ (Supabase en producción), todo en el esquema `riego` | [backend/README.md](backend/README.md#base-de-datos) |
| Modelo | `ml/` | `riego_ml` (pandas, LightGBM) | [ml/README.md](ml/README.md) |

- **Sesión**: access token JWT solo en memoria del navegador (30 min) y refresh token en la cookie
  HttpOnly `rt` (7 días, `SameSite=Strict`). Login, refresh y logout solo se aceptan desde los
  orígenes de `CORS_ORIGINS`/`FRONTEND_URL` del backend.
- **Base de datos**: la app se conecta con el rol `riego_app` (no dueño, sujeto a RLS); Alembic y la
  CLI de administración usan el rol dueño por `DATABASE_URL_MIGRACIONES`. Funciona igual contra un
  Postgres local o contra Supabase (pooler 6543 en modo transacción).
- **Zona horaria**: todo lo visible está en hora de Lima (America/Lima).

## Estado por fases

| Fase | Contenido | Estado |
|---|---|---|
| F1 Base | Esquema completo, autenticación, usuarios, auditoría, correos, layout y pantallas de acceso | Lista |
| F2 Datos | Riego aplicado (Excel), ingesta WeatherLink/Phytech, frescura de datos | Próxima |
| F3 Modelo | Generar cronogramas, listado y detalle | Próxima |
| F4 Flujo | Corrección, publicación, Visto del programador, notificaciones | Próxima |
| F5 Gráficos | Dashboard con KPIs, Datos de campo, exportaciones | Próxima |

## Cómo levantar todo en desarrollo

Requisitos: Python 3.11, Node 24 y npm 11, PostgreSQL 15 o superior (local) o un proyecto de
Supabase. Los comandos son para Git Bash en Windows; en PowerShell cambia `/` por `\`.

### 1. Backend: entorno y configuración

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # incluye ../ml/requirements.txt
.venv/Scripts/python -m pip install -e ../ml                   # paquete riego_ml
cp .env.example .env
```

En `backend/.env` completa, como mínimo (cada variable está comentada en `.env.example`):

| Variable | Valor en desarrollo local |
|---|---|
| `DATABASE_URL_MIGRACIONES` | `postgresql+psycopg://postgres@localhost:5432/riego_dev` |
| `RIEGO_APP_PASSWORD` | una contraseña de al menos 16 caracteres para el rol `riego_app` |
| `DATABASE_URL` | `postgresql+psycopg://riego_app:<RIEGO_APP_PASSWORD>@localhost:5432/riego_dev` |
| `JWT_SECRET` | `.venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `COOKIE_SECURE` | `false` (sin HTTPS el navegador no guarda la cookie del refresh) |
| `FRONTEND_URL` / `CORS_ORIGINS` | `http://localhost:5173` / `http://localhost:5173,http://127.0.0.1:5173` |

### 2. Base de datos

```bash
"/c/Program Files/PostgreSQL/18/bin/psql.exe" -h localhost -U postgres \
    -c "CREATE DATABASE riego_dev ENCODING 'UTF8' TEMPLATE template0"   # solo la primera vez

.venv/Scripts/python -m alembic upgrade head          # esquema riego, RLS, rol riego_app y datos semilla
.venv/Scripts/python -m app.cli configurar-rol-app    # da LOGIN y contraseña a riego_app (RIEGO_APP_PASSWORD)
.venv/Scripts/python -m app.cli verificar-seguridad-bd
.venv/Scripts/python -m app.cli crear-admin           # primer administrador (pide datos y contraseña)
```

Para Supabase, el orden es el mismo; las URLs cambian (conexión directa 5432 para migraciones y
pooler 6543 para la app). Ver [backend/README.md](backend/README.md#supabase).

### 3. API y tareas

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000   # http://localhost:8000/docs
.venv/Scripts/python -m app.jobs                                     # en otra terminal: envío de correos
```

En desarrollo puedes omitir el segundo proceso con `SCHEDULER_ENABLED=true` en `.env`. Sin
`SMTP_HOST`, los correos (por ejemplo, el de recuperar contraseña) se guardan como `.eml` en
`backend/var/correos/`.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (puerto fijo)
```

Vite reenvía `/api` al backend en `:8000`, así que el navegador ve un solo origen. Abre la app en
`http://localhost:5173` o `http://127.0.0.1:5173`: son los orígenes que el backend acepta para
login, refresh y logout. Si usas otro puerto u otro host, agrégalo a `CORS_ORIGINS` en
`backend/.env`; si no, el backend responde 403 «Solicitud no permitida». Si el puerto 5173 está
ocupado, Vite se detiene con un error en vez de cambiar de puerto en silencio.

### 5. Pruebas

```bash
cd backend && .venv/Scripts/python -m pytest -q     # usa la base riego_test (se crea y migra sola)
cd frontend && npx vitest run && npm run build
```

## Estructura

```text
backend/    API FastAPI, migraciones Alembic, tareas programadas y CLI de administración
frontend/   Aplicación React + Vite
ml/         Extracción, procesamiento y modelos (riego_ml)
docs/       Propuesta del MVP, guía de usuario, documentación de APIs y papers
```

## Machine learning

Predice el plan de riego diario de cada turno del módulo 5 de ENSUEÑO 1: número de ciclos y,
por ciclo, m3/ha, duración y horario (con rangos de confianza). Pipeline:
Phytech crudo → unir (riego + meteo + Phytech) → preparar → entrenar → predecir.

```powershell
python -m venv ml/.venv
ml\.venv\Scripts\Activate.ps1
pip install -r ml/requirements.txt
python ml/src/riego_ml/pipelines/ejecutar_todo.py   # entrena (pasos 1-3)
python ml/src/riego_ml/pipelines/predecir.py        # plan del día siguiente
```

- Detalle técnico, modelos y métricas: [ml/README.md](ml/README.md)
- Operación del piloto (rutinas diaria, semanal y mensual): [ml/OPERACION.md](ml/OPERACION.md)

Los scripts de extracción viven en `ml/src/riego_ml/data_extraction/` y están ignorados por git.
Las credenciales se pasan como variables de entorno en la sesión, no se leen desde un archivo `.env`:

```powershell
$env:PHYTECH_API_KEY="..."
$env:PHYTECH_API_SECRET="..."
$env:WEATHERLINK_API_KEY="..."
$env:WEATHERLINK_API_SECRET="..."
python ml/src/riego_ml/data_extraction/descargar_phytech.py
python ml/src/riego_ml/data_extraction/descargar_weatherlink.py
```

Salidas: `ml/data/raw/phytech/`, `ml/data/raw/WeatherLink/`, `ml/cache/`, `ml/logs/`.

## Seguridad

No se versionan credenciales, archivos `.env`, datos descargados, cachés, logs ni los scripts de
extracción. Contraseñas con argon2id, tokens de un solo uso guardados como SHA-256, auditoría de
cada acción relevante y RLS en todas las tablas. Detalle en [backend/README.md](backend/README.md#autenticación-y-seguridad-7).
