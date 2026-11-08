# Sistema de Plan de Riego · Grupo El Rocío

Aplicación web de AvoPeru y Talsa para el plan de riego diario del fundo ENSUEÑO 1 (módulo
EN01-MOD5, turnos TE01–TE05). Un modelo entrenado con el historial de riego, clima (WeatherLink)
y sensores de suelo y planta (Phytech) propone cada día el número de ciclos, los m³/ha, la duración
y el horario por turno. El encargado revisa el plan y lo publica, y el programador lo confirma en
campo. El subgerente revisa y puede pedir correcciones, y el administrador gestiona los usuarios.

- Especificación completa: [`docs/propuesta_mvp.md`](docs/propuesta_mvp.md).
- Guía para quienes usan el sistema, por rol: [`docs/guia_usuario.md`](docs/guia_usuario.md).

## Estado por fases

| Fase | Contenido | Estado |
|---|---|---|
| F1 Base | Esquema completo de la BD (RLS, rol `riego_app`, semillas), autenticación, recuperación y cambio de contraseña, usuarios, auditoría, cola de correos, CLI de administración. Frontend: tema, login, layout, usuarios y auditoría | **Lista** |
| F2 Datos | Carga histórica idempotente, ingesta diaria WeatherLink/Phytech (05:00 Lima y «Actualizar ahora»), conversión de unidades de WeatherLink, `ambiente_diario` e Historial desde la BD (paridad con `riego_ml`), riego aplicado (consulta, versiones y carga de Excel con vista previa), frescura de datos en el Dashboard, series de datos de campo (API) | **Lista** |
| F3 Predicción | Carga del modelo con sha256, bucle de generación desde la BD (idéntico a `planificar` de `riego_ml`), foto de entradas y alternativas de 1 a 5 ciclos, versiones y marcas (preliminar, datos incompletos, regenerado, desactualizado), regenerar. Frontend: Generar, listado y detalle de cronogramas en lectura, «Hoy y mañana» en el Dashboard | **Lista** |
| F4 Flujo | Corrección con motivo y recálculo, publicación y borrador de cambios, Visto, solicitud de corrección y mantener versión, riego provisional y edición manual, línea de tiempo y correos. Frontend: flujo por rol, datos y comparación de versiones, filtros y estado de mañana | **Lista** |
| F5 Gráficos | KPIs del Dashboard (agua aplicada ayer, aplicado vs modelo, MDS, ETo, estado de mañana) y pronóstico Phytech; Datos de campo con gráficos (agua aplicada vs propuesta por turno, MDS y crecimiento, suelo por profundidad con línea de estrés, clima); exportación del cronograma a PDF y Excel; CSV de refinamiento (admin) | **Lista** |
| F6 PWA y pulido | Instalable como aplicación (manifest, íconos verdes y service worker base sin caché de datos), revisión a 360 px de todas las pantallas, accesibilidad (nombres accesibles, un `h1` por pantalla), sin pantallas provisorias, guía de usuario final | **Lista** |

Todas las fases del MVP están listas. Qué puede hacer cada rol: [`docs/guia_usuario.md`](docs/guia_usuario.md).

## Arquitectura

```text
Navegador ──► Frontend React (Vite)   ──/api/v1──► API FastAPI (1 worker) ──► PostgreSQL / Supabase
              frontend/ :5173 (dev)                 backend/app :8000          esquema `riego`
              proxy de Vite: /api → :8000            │                          (RLS, rol riego_app)
                                                     └── riego_ml (ml/src): saneo de datos y
                                                         ambiente_diario (F2), predicciones (F3)
              Proceso de tareas (python -m app.jobs): cola de correos, mantenimiento diario
              y, desde la fase 2, la ingesta de las 05:00 (Lima)
```

| Pieza | Carpeta | Tecnología | Detalle |
|---|---|---|---|
| Frontend | `frontend/` | React 19, TypeScript estricto, Vite 8, Tailwind 4, TanStack Query/Table, Radix | [frontend/README.md](frontend/README.md) |
| API | `backend/app/` | FastAPI, SQLAlchemy 2, psycopg 3, Pydantic v2, PyJWT, argon2 | [backend/README.md](backend/README.md) |
| Tareas programadas | `backend/app/jobs/` | APScheduler, en un proceso aparte (o dentro de la API en desarrollo) | [backend/README.md](backend/README.md#correos-y-tareas-programadas) |
| Base de datos | `backend/alembic/` | PostgreSQL 15 o superior (Supabase en producción), todo en el esquema `riego` | [backend/README.md](backend/README.md#base-de-datos) |
| Modelo | `ml/` | `riego_ml` (pandas, LightGBM), instalado en el venv del backend con `pip install -e ../ml` | [ml/README.md](ml/README.md) |

- **Sesión**: el access token JWT (30 min) vive solo en la memoria del navegador. El refresh
  token va en la cookie HttpOnly `rt` (7 días, `SameSite=Strict`, `Path=/api/v1/auth`). El
  backend acepta login, refresh y logout solo desde los orígenes de `CORS_ORIGINS`, o de
  `FRONTEND_URL` si esa variable está vacía.
- **Base de datos**: la app se conecta con el rol `riego_app`, que no es dueño y está sujeto a
  RLS; al arrancar comprueba que la conexión use ese rol. Alembic, `configurar-rol-app` y
  `verificar-seguridad-bd` usan el rol dueño por `DATABASE_URL_MIGRACIONES`. Funciona igual
  contra un Postgres local o contra Supabase (pooler 6543 en modo transacción).
- **Zona horaria**: todo lo visible está en hora de Lima (America/Lima).

## Cómo levantar todo en desarrollo (Postgres local)

**Requisitos**: Python 3.11 (el modelo se entrenó con 3.11.9), Node 24 y npm 11, y PostgreSQL 15
o superior en `localhost:5432` (se probó con PostgreSQL 18 y autenticación `trust` para
`postgres`). Los comandos son para Git Bash en Windows; en PowerShell cambia `/` por `\`.

### 1. Entorno de Python y dependencias

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # incluye requirements.txt y ../ml/requirements.txt
.venv/Scripts/python -m pip install -e ../ml                   # paquete riego_ml (solo empaquetado)
```

La instalación trae también el stack de ML (LightGBM, XGBoost, CatBoost...) y puede tardar varios
minutos. Todas las versiones están fijas.

### 2. Configuración (`backend/.env`)

```bash
cp .env.example .env
```

`backend/.env` no se versiona. Cada variable está comentada en `.env.example`. Para desarrollo local
completa como mínimo:

| Variable | Valor en desarrollo local |
|---|---|
| `DATABASE_URL_MIGRACIONES` | `postgresql+psycopg://postgres@localhost:5432/riego_dev` |
| `RIEGO_APP_PASSWORD` | una contraseña de al menos 16 caracteres para el rol `riego_app` |
| `DATABASE_URL` | `postgresql+psycopg://riego_app:<RIEGO_APP_PASSWORD>@localhost:5432/riego_dev` |
| `JWT_SECRET` | salida de `.venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `COOKIE_SECURE` | `false` (sin HTTPS el navegador no guarda la cookie del refresh) |
| `FRONTEND_URL` | `http://localhost:5173` |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` |

Si la contraseña de `riego_app` tiene caracteres como `@`, `:`, `/` o `#`, escríbelos en
`DATABASE_URL` con su código URL (`%40`, `%3A`, `%2F`, `%23`). Lo más simple es generar una solo
con letras y números. El resto de las variables (SMTP, modelo) puede quedar con su valor de
ejemplo. Para la ingesta de F2 completa `WEATHERLINK_API_KEY/SECRET` y `PHYTECH_API_KEY/SECRET`
(los IDs de estación, área, plot y project ya traen los del MOD5); sin ellas la ingesta termina en
error «configuración» y el resto de la app funciona igual. `INGESTA_HORA` (05:00) fija la tarea
diaria.

### 3. Bases de datos

```bash
PSQL="/c/Program Files/PostgreSQL/18/bin/psql.exe"
"$PSQL" -h localhost -U postgres -c "CREATE DATABASE riego_dev ENCODING 'UTF8' TEMPLATE template0"
```

`riego_dev` es la base de desarrollo y se crea solo la primera vez. La de pruebas, `riego_test`, no
hace falta crearla: la suite de pytest la crea y la migra sola. Para usar otra base, cambia
`TEST_DATABASE_URL`.

### 4. Migraciones, rol de la app y primer administrador

```bash
.venv/Scripts/python -m alembic upgrade head          # esquema riego, RLS, rol riego_app (NOLOGIN) y datos semilla
.venv/Scripts/python -m app.cli configurar-rol-app    # da LOGIN a riego_app con la contraseña de RIEGO_APP_PASSWORD
.venv/Scripts/python -m app.cli verificar-seguridad-bd   # debe responder "OK"; si no, sale con código 1
.venv/Scripts/python -m app.cli crear-admin           # pide usuario, nombre, correo y contraseña (sin mostrarla)
```

El orden importa. `crear-admin` se conecta como `riego_app` (igual que la app), así que necesita
que antes hayas corrido `configurar-rol-app`. La contraseña del administrador debe tener al menos
10 caracteres, con letras y números, y no puede ser igual al usuario. Con `--temporal`, obliga a
cambiarla en el primer ingreso. Las opciones sin preguntas para scripts están en
[backend/README.md](backend/README.md#primer-administrador).

### 5. API y tareas programadas

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000   # http://localhost:8000/docs
.venv/Scripts/python -m app.jobs                                     # en otra terminal: cola de correos
```

- `GET http://localhost:8000/api/v1/health` debe responder `"status":"ok"`, `"bd":"ok"` y
  `"rol_bd":"ok"`.
- En desarrollo puedes omitir el segundo proceso poniendo `SCHEDULER_ENABLED=true` en `.env`. Para
  procesar la cola una sola vez, usa `python -m app.jobs --una-vez`.
- Sin `SMTP_HOST`, los correos (por ejemplo, el de recuperar contraseña) se guardan como `.eml` en
  `backend/var/correos/`. Ábrelos con cualquier cliente de correo para ver el enlace.

### 6. Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (puerto fijo)
```

Vite reenvía `/api` al backend en `:8000`, así que el navegador ve un solo origen y
`VITE_API_URL` queda vacía. Abre la app en `http://localhost:5173` o `http://127.0.0.1:5173`, que
son los orígenes permitidos en `CORS_ORIGINS`, e ingresa con el administrador del paso 4.

Si usas otro puerto u otro host, agrégalo a `CORS_ORIGINS` y reinicia el backend; si no, el login
responde 403 «Solicitud no permitida». Si el puerto 5173 está ocupado, Vite se detiene con un
error en vez de cambiar de puerto sin avisar.

### 7. Pruebas

```bash
cd backend && .venv/Scripts/python -m pytest -q     # base riego_test (se crea y migra sola)
cd frontend && npx vitest run && npm run build
```

La suite del backend nunca llama a las APIs reales (deja las claves vacías y usa transportes
simulados) e incluye la paridad de `ambiente_diario` e Historial contra la ruta por archivos de
`riego_ml` cuando están los datos de `ml/data/raw`.

### 8. Datos de campo (F2): histórico, ingesta y prueba

> **Cuidado**: si tu `backend/.env` apunta a Supabase (producción), exporta antes la base local en
> la misma terminal; las variables de entorno tienen prioridad sobre `.env`:
>
> ```bash
> export DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/riego_dev
> export DATABASE_URL_MIGRACIONES=$DATABASE_URL
> ```

```bash
cd backend
# 1. Carga histórica (idempotente: repetirla no inserta ni cambia nada). Lee de ml/data/raw las
#    rutas de ml/config/pipeline.yaml: clima, Phytech suelo/planta, NDVI y riego histórico (MOD5).
.venv/Scripts/python -m app.cli cargar-historico                   # ~3 min, todas las fuentes
# 2. Ingesta de las APIs (rango automático: última fecha guardada − 3 días hasta ayer, hora de Lima)
.venv/Scripts/python -m app.cli ingestar
.venv/Scripts/python -m app.cli ingestar --fuentes weatherlink --desde 2026-11-05 --hasta 2026-11-07
# 3. Si cambia una regla de conversión de WeatherLink (°F/pulgadas/millas → °C/mm/km, en
#    app/integraciones/weatherlink/conversion.py), re-deriva sin volver a descargar:
.venv/Scripts/python -m app.cli reprocesar-weatherlink --desde 2026-11-01 --hasta 2026-11-07
```

- **Tarea diaria**: `python -m app.jobs` lanza la ingesta a las `INGESTA_HORA` (05:00 Lima); en
  desarrollo puede correr dentro de la API con `SCHEDULER_ENABLED=true`. Cada corrida queda en
  `ingesta_corrida` y cada llamada en `ingesta_crudo` (sin claves ni token).
- **Desde la web**: el Dashboard muestra la **Frescura de datos** por fuente (verde hasta ayer,
  naranja si falta algo, huecos) y, para administrador y encargado, **Actualizar ahora**, que lanza
  la misma ingesta en segundo plano y muestra el avance; administrador, encargado y subgerente ven
  las **Últimas corridas**.
- **Riego aplicado → Cargar Excel**: sube el Excel del controlador (hoja `MOD5`, p. ej.
  `ml/data/raw/data_riego.xlsx`), revisa la vista previa (nuevo, igual, reemplaza provisional,
  reemplaza aplicado, sin riego, error), desmarca lo que no quieras y **Confirmar**. Nada se
  guarda hasta confirmar; la vista previa vence a las 24 h. Subir otra vez el archivo acumulado
  solo da «igual».
- **Probar con claves reales**: exporta la base local como arriba, deja las claves en
  `backend/.env` y pide rangos chicos (las APIs solo se leen). Detalle, conteos de la prueba real y
  conversión medida: [backend/README.md](backend/README.md#datos-de-campo-f2).

## Apuntar a Supabase

El orden es el mismo que en local; solo cambian las URLs de `backend/.env`:

1. `DATABASE_URL_MIGRACIONES`: rol `postgres` por el puerto **5432**. Puede ser la conexión directa
   (`db.<ref>.supabase.co`) o, desde redes que solo tienen IPv4, el *Session pooler*
   (`aws-0-<region>.pooler.supabase.com:5432`). Para migrar, se rechaza el pooler en modo
   transacción (6543).
2. Ejecuta `alembic upgrade head`, `configurar-rol-app` y `verificar-seguridad-bd`. Si no hay
   conexión posible, `alembic upgrade head --sql` genera el SQL para pegarlo en el editor de
   Supabase.
3. `DATABASE_URL`: pooler en modo transacción (puerto **6543**) con el usuario `riego_app.<ref>` y
   la contraseña de `RIEGO_APP_PASSWORD`. El backend detecta el 6543 y usa `NullPool` sin
   *prepared statements*. Todas las tablas llevan el esquema `riego`, así que no depende del
   `search_path`.
4. Ejecuta `crear-admin`.

La Data API de Supabase solo publica `public`, así que el esquema `riego` queda fuera de ella, y
`anon` y `authenticated` no reciben privilegios ni políticas. Detalle y comandos en
[backend/README.md](backend/README.md#supabase).

**En producción** (`APP_ENV=production`), la API no arranca si falta algo de lo siguiente:
- `DEBUG=false`, `COOKIE_SECURE=true` y `COOKIE_SAMESITE=strict`;
- un `JWT_SECRET` de 32 caracteres o más;
- `FRONTEND_URL` con https y `CORS_ORIGINS` vacío o igual a `FRONTEND_URL`;
- una conexión con el rol `riego_app`.

Se arranca con `python -m app`, que usa 1 worker y toma la IP real solo desde `TRUSTED_PROXIES`.
Frontend y API deben quedar bajo el mismo dominio (decisión D6).

## Estructura

```text
backend/    API FastAPI, migraciones Alembic, tareas programadas y CLI de administración
frontend/   Aplicación React + Vite
ml/         Extracción, procesamiento y modelos (riego_ml)
docs/       Propuesta del MVP, guía de usuario, documentación de APIs y papers
```

## Machine learning

Predice el plan de riego diario de cada turno del módulo 5 de ENSUEÑO 1: el número de ciclos y,
por ciclo, los m³/ha, la duración y el horario, con rangos de confianza. El pipeline es:
Phytech crudo → unir (riego + meteo + Phytech) → preparar → entrenar → predecir. Desde F2 la web
usa sus reglas de saneo (`riego_ml.sources`, separadas de la lectura de archivos por la decisión
D1) y `construir_ambiente_diario` para guardar los datos de campo, y `PlanRiego.predecir` para generar los cronogramas (F3).

```powershell
python -m venv ml/.venv            # o usa backend/.venv, que ya trae ml/requirements.txt
ml\.venv\Scripts\Activate.ps1
pip install -r ml/requirements.txt
python ml/src/riego_ml/pipelines/ejecutar_todo.py   # entrena (pasos 1-3)
python ml/src/riego_ml/pipelines/predecir.py        # plan del día siguiente
```

- Detalle técnico, modelos y métricas: [ml/README.md](ml/README.md)
- Operación del piloto (rutinas diaria, semanal y mensual): [ml/OPERACION.md](ml/OPERACION.md)

Los scripts de extracción viven en `ml/src/riego_ml/data_extraction/` y git los ignora. Las
credenciales se pasan como variables de entorno de la sesión; no se leen de un archivo `.env`:

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
extracción. Las contraseñas se guardan con argon2id y los tokens de un solo uso como SHA-256. Cada
acción relevante queda en la auditoría, y todas las tablas tienen RLS. Detalle en
[backend/README.md](backend/README.md#autenticación-y-seguridad-7).
