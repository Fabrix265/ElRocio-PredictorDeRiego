# Backend – Sistema de Plan de Riego (Grupo El Rocío)

API FastAPI + SQLAlchemy 2 (psycopg 3) + Alembic sobre PostgreSQL (Supabase en producción).
Especificación: [`docs/propuesta_mvp.md`](../docs/propuesta_mvp.md).

```text
app/
  main.py            create_app: CORS, cabeceras de seguridad, manejo de errores, routers, lifespan
  api/deps.py        DbSesion (unidad de trabajo), usuario_actual (JWT + BD), requiere_rol(...)
  api/v1/endpoints/  health, auth, usuarios, auditoria, catalogo (+ /modulos/{id}/turnos), riego,
                     datos (frescura y series), ingestas
  core/              config, security (argon2id, JWT), tiempo (hoy_lima), logging (redacción),
                     middleware (cabeceras), errores (mensajes en español)
  services/          auth_service, usuario_service, auditoria_service, correo_service, rate_limit,
                     lecturas_service, ambiente_service, carga_historica, riego_contenido,
                     ingesta_service (APIs), datos_service (frescura, series, caudal)
  repositories/      consultas SQLAlchemy (usuarios, sesiones, intentos, auditoria, correos,
                     catalogo, datos_campo, riego, ingestas, datos_series)
  integraciones/     http.py (reintentos, errores sin secretos), weatherlink/ (cliente v2 y
                     conversion.py: °F/pulgadas/millas → °C/mm/km), phytech/ (cliente con token
                     en memoria y adaptador a las tablas de riego_ml)
  ml/                columnas.py (mapeo BD ↔ riego_ml), historial_bd.py (BD → Historial, §2.3)
  models/ · db/      tablas del esquema riego, motor y sesiones
  emails/            plantillas Jinja2 (marca verde y blanca) y envío SMTP / archivo
  jobs/              APScheduler: cola de correos, mantenimiento e ingesta diaria (python -m app.jobs)
  cli.py             configurar-rol-app, verificar-seguridad-bd, crear-admin, cargar-historico,
                     recalcular-ambiente, ingestar, reprocesar-weatherlink
```

### Convención de transacciones y capas (desde F2)

- **Servicios** (`services/`): reglas y permisos; hacen `flush`, **nunca** `commit`.
- **Quien llama confirma**: en los endpoints, la dependencia `DbSesion`
  (`api/deps.unidad_de_trabajo`, `scope="function"`) hace `commit` cuando el endpoint termina
  sin error, *antes* de enviar la respuesta, y `rollback` si lanza una excepción. La CLI y las
  tareas usan `with unidad_de_trabajo() as db:` (`db/session.py`).
- **Excepciones documentadas** (lo que debe persistir aunque la operación termine en error):
  `rate_limit.reservar` (el intento se ve antes de contar), la auditoría del login o cambio de
  contraseña fallidos, la revocación de una familia de refresh por reuso, y el procesamiento de la
  cola de correos (reclamo confirmado antes de enviar; cada envío es su propia transacción).
  También el paso de una carga de Excel a `vencida` antes de responder 409.
- **Consultas** en `repositories/` (SQLAlchemy); los servicios no arman `select`/`update`.

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
- `JWT_SECRET`: al menos 32 caracteres aleatorios
  (`.venv/Scripts/python -c "import secrets; print(secrets.token_urlsafe(48))"`).
- En desarrollo local sin HTTPS: `COOKIE_SECURE=false` (si no, el navegador no guarda la cookie
  del refresh). En producción la configuración exige `COOKIE_SECURE=true`, `DEBUG=false`,
  `FRONTEND_URL` con https y un `JWT_SECRET` largo; si falta algo, la app no arranca.

Para ejecutar sin leer `backend/.env`, exporta **`RIEGO_SIN_ENV_FILE=1` en el entorno del
proceso antes de arrancar** la API, CLI, tareas o Alembic. También acepta `true`, `si` y `sí`
(sin distinguir mayúsculas y omitiendo espacios). No sirve ponerla dentro de `.env`: la decisión
se toma antes de abrirlo. Sin esa variable se mantiene la lectura habitual, con prioridad para
las variables del entorno. Al omitir el archivo, configura en el entorno las conexiones locales
y demás valores necesarios; las credenciales de API ausentes quedan vacías.

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
- `0003_endurecimiento`: tipo de intento `cambiar_password`, gracia única del refresh
  (`sesion_refresh.gracia_usada_at`), `riego_registro` inmutable (la app solo puede pasar
  `vigente` de true a false; no borra ni reescribe versiones, también por trigger) y
  `updated_at` mantenido por trigger (`riego.fijar_updated_at`, cubre upserts y SQL directo).
- `0004_ingesta_exclusion_latido`: `ingesta_corrida.latido_at` e índice único parcial
  `uq_ingesta_corrida_en_curso (fuente) WHERE estado = 'en_curso'` (una sola corrida en curso por
  fuente; antes de crearlo cierra como interrumpidas las repetidas).
- `alembic downgrade base` deja el esquema vacío (conserva `riego.alembic_version` y el rol).
- `configurar-rol-app` solo hace `ALTER ROLE riego_app WITH LOGIN PASSWORD ...` (los demás
  atributos los fija la migración 0001; así funciona con un dueño no superusuario, como en
  Supabase), cifra la contraseña (SCRAM-SHA-256) en el cliente y se niega si `riego_app` tiene
  SUPERUSER, BYPASSRLS, CREATEROLE o CREATEDB.
- `verificar-seguridad-bd` termina con código 1 si alguna tabla quedó sin RLS, con políticas para
  otros roles, con privilegios para `PUBLIC`/`anon`/`authenticated` (también EXECUTE sobre
  funciones), si `riego_app` tiene privilegios de más o le faltan SELECT/INSERT, o falta algún
  trigger.
- **Migraciones nuevas (F2–F5)**: cada tabla nueva con `preparar_tabla("tabla", modo="crud"|
  "insercion")` y cada función con `preparar_funcion("nombre(args)")` (`app/db/migraciones.py`):
  GRANT para `riego_app`, RLS con su política, secuencias, y nada para PUBLIC/`anon`/
  `authenticated`. Postgres no aplica los `ALTER DEFAULT PRIVILEGES IN SCHEMA ... REVOKE` sobre el
  EXECUTE de PUBLIC, así que sin estas ayudas una función nueva nacería ejecutable por todos.

### Supabase

1. `DATABASE_URL_MIGRACIONES` con el rol `postgres` y el puerto 5432:
   - conexión directa `postgresql://postgres:<clave>@db.<ref>.supabase.co:5432/postgres` (solo
     IPv6 si el proyecto no tiene el complemento IPv4), o
   - *Session pooler* `postgresql://postgres.<ref>:<clave>@aws-0-<region>.pooler.supabase.com:5432/postgres`
     (funciona por IPv4 y admite DDL; usar este desde redes o hosting solo IPv4).
   El pooler en modo transacción (6543) se rechaza para migrar.
2. `alembic upgrade head`, luego `configurar-rol-app` y `verificar-seguridad-bd`.
   Sin conexión posible: `PYTHONUTF8=1 .venv/Scripts/python -m alembic upgrade head --sql > riego.sql`
   genera el SQL completo (con los datos semilla) para pegarlo en el editor SQL de Supabase; luego
   `ALTER ROLE riego_app WITH LOGIN PASSWORD '<clave>';` desde el mismo editor.
3. `DATABASE_URL` = pooler 6543 con el usuario `riego_app.<ref>` y la contraseña definida. La API
   comprueba al arrancar que se conecta como `riego_app` (sin SUPERUSER, BYPASSRLS ni ser dueño
   del esquema): en producción no arranca si no; en desarrollo avisa en el log y `/health` queda
   `degradado` con `rol_bd: "inseguro"`.
4. `crear-admin` (abajo) para el primer administrador.

La Data API de Supabase solo publica `public`; el esquema `riego` queda fuera y, además, sin
privilegios ni políticas para `anon`/`authenticated`.

### Primer administrador

```bash
.venv/Scripts/python -m app.cli crear-admin                 # pregunta los datos y la contraseña (sin mostrarla)
.venv/Scripts/python -m app.cli crear-admin --username admin --nombre "Administrador" --correo admin@empresa.com
echo "$CLAVE" | .venv/Scripts/python -m app.cli crear-admin --username admin --nombre "Administrador" \
    --correo admin@empresa.com --password-stdin             # para scripts
```

Usa `DATABASE_URL` (rol `riego_app`, igual que la app). La contraseña debe cumplir la política
(mínimo 10 caracteres, letras y números, distinta del usuario). `--temporal` obliga a cambiarla en
el primer ingreso. Queda auditado como `usuario_creado` con actor `sistema`.

## Ejecución

```bash
# Desarrollo
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Producción (detrás de un proxy; 1 worker: el modelo usa todos los núcleos)
.venv/Scripts/python -m app        # HOST/PORT del entorno (por defecto 0.0.0.0:8000)
```

- **IP real**: `python -m app` arranca uvicorn con `--proxy-headers` y
  `--forwarded-allow-ips=TRUSTED_PROXIES` leído de `backend/.env`: la IP del cliente se toma de
  `X-Forwarded-For` solo si la conexión viene de un proxy de confianza. La app nunca lee
  `X-Forwarded-For` por su cuenta; esa IP es la que se audita y la que cuentan los límites. En
  producción avisa si `TRUSTED_PROXIES` quedó en `127.0.0.1` (detrás de un PaaS todos los clientes
  tendrían la IP del proxy y el límite por IP sería global).
- `GET /api/v1/health` → `{status, app, entorno, bd, rol_bd, migraciones, modelo}` (503 si la BD no
  responde; `status: "degradado"` si el rol de la conexión no es `riego_app` o tiene privilegios de
  más, o si `migraciones` es `"pendientes"`).
- **Migraciones pendientes:** si el código es más nuevo que la BD (p. ej. tras actualizar el repo sin
  `alembic upgrade head`), el arranque lo avisa con un ERROR en el log que dice qué migración falta,
  y las consultas que tocan una columna o tabla inexistente responden 503 «La base de datos no está
  actualizada…» en vez de un 500 genérico. Solución: desde `backend/`, `.venv/Scripts/python -m alembic upgrade head`
  contra la BD que usa la API (usa `DATABASE_URL_MIGRACIONES`).
- `DEBUG=true` solo cambia el nivel de log: los errores no controlados nunca devuelven el
  traceback al cliente.
- Documentación interactiva en `http://localhost:8000/docs` (deshabilitada en producción).

## Autenticación y seguridad (§7)

| Ruta (`/api/v1`) | Descripción |
|---|---|
| `POST /auth/login` | `{username, password}` → `{access_token, token_type, expires_in, usuario}` + cookie `rt` |
| `POST /auth/refresh` | Cookie `rt` + `X-Requested-With: fetch` → mismo cuerpo; rota la cookie |
| `POST /auth/logout` | Cookie `rt` + `X-Requested-With: fetch` → 204; revoca la familia |
| `POST /auth/recuperar` | `{identificador}` (usuario o correo) → 202 siempre con el mismo mensaje |
| `POST /auth/restablecer` | `{token, password}` → 204; 400 si el enlace no sirve |
| `GET /auth/me`, `POST /auth/cambiar-password` | Perfil; cambio (devuelve tokens nuevos) |
| `GET/POST /usuarios`, `GET/PATCH /usuarios/{id}`, `POST /usuarios/{id}/password-temporal` | Solo admin |
| `GET /auditoria`, `GET /auditoria/opciones` | Admin y subgerente |
| `GET /fundos`, `GET /motivos-correccion` | Cualquier usuario con sesión |

- Contraseñas con argon2id. Access token JWT HS256 (30 min) con `sub`, `ver`, `iat`, `exp`, `typ`,
  `iss`, `aud`; en cada petición se lee el usuario de la BD: si está inactivo o cambió su
  `token_version` (desactivado, cambio de rol, cambio o restablecimiento de contraseña), el token
  deja de servir al instante.
- Refresh token opaco (7 días) en la cookie `rt` (`HttpOnly`, `Secure` según `COOKIE_SECURE`,
  `SameSite` según `COOKIE_SAMESITE`, `Path=/api/v1/auth`); en la BD solo su SHA-256. Cada uso
  extiende la sesión 7 días, con un tope de 30 días desde el login. Reusar un refresh ya rotado:
  dentro de 30 s (respuesta perdida) entrega **una sola vez** un sucesor y revoca la hoja anterior
  (nunca hay más de una sesión activa por familia); un segundo reuso, uno fuera de plazo o usar la
  hoja revocada por la gracia revocan toda la familia. Refresh y logout exigen
  `X-Requested-With: fetch` y validan `Origin`.
- Mientras `debe_cambiar_password` sea true, todo responde 403 «Debes cambiar tu contraseña»
  salvo `me`, `cambiar-password` y `logout`.
- Límites contados en la BD (`intento_login`): login 5 fallos/15 min por usuario+IP, 30 por IP,
  10 por usuario; recuperar 3/h por usuario y 10/h por IP; restablecer 10/15 min por IP; cambiar
  contraseña 5 fallos/15 min por usuario (al quinto se cierran todos sus accesos: podría ser un
  access token robado). El intento se registra (con commit) **antes** de verificar la contraseña,
  así las peticiones simultáneas se cuentan entre sí. El usuario intentado se guarda como
  HMAC-SHA256, nunca el texto escrito. Usuario inexistente: se verifica contra un hash ficticio y
  el mensaje es siempre el mismo.
- IDs y páginas acotados (`IdPath`, `IdQuery`, `Pagina` en `app/api/deps.py`; usarlos en F2–F5):
  fuera de rango responden 422.
- Producción exige además `COOKIE_SAMESITE=strict` y `CORS_ORIGINS` vacío o igual a
  `FRONTEND_URL`; `CORS_ORIGINS=*` se rechaza siempre.
- Errores siempre como `{"detail": "mensaje en español"}`; los de validación (422) como lista
  `[{loc, msg, type}]` con `msg` en español y sin repetir lo enviado.
- Cabeceras: `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, CSP
  `frame-ancestors 'none'`, `Cache-Control: no-store` y HSTS solo en producción.
- Logs: un filtro redacta contraseñas, tokens, `Authorization`, `X-Api-Secret`, cookies,
  `api-key=`, claves con prefijo o sufijo (`phytech_api_secret=`, `secret_key:`, `token_hash`,
  `api-signature=`...) y cualquier JWT; httpx/httpcore en WARNING.
- Auditoría de login, login_fallido, logout, recuperar_solicitado, password_restablecido,
  password_cambiado, password_cambio_fallido, usuario_creado/editado, rol_cambiado,
  usuario_activado/desactivado y password_temporal_asignado, con antes/después en lista blanca
  (nunca hashes ni tokens). Un login fallido de un usuario inexistente se audita sin usuario (lo
  escrito podría ser una contraseña); `recuperar_solicitado` va sin actor (es anónimo).
- Cambiar la contraseña, asignar una temporal, cambiar el rol, desactivar o cambiar el correo
  invalidan los enlaces de recuperación pendientes.

## Datos de campo (F2)

Las tablas guardan la salida **saneada** de `riego_ml` (las reglas viven en
`ml/src/riego_ml/sources`, separadas de la lectura de archivos por la decisión D1):

| Tabla | Contenido | Escribe |
|---|---|---|
| `meteo_lectura` | Salida de `sanear_meteo` (30 min, °C, mm, km), origen `excel_historico` o `weatherlink` | `lecturas_service.guardar_meteo` (la API nunca pisa el Excel histórico) |
| `phytech_suelo_horario` / `phytech_planta_diario` | Formato de las hojas `Suelo_horario` / `Planta_diario` | `guardar_suelo` / `guardar_planta` |
| `ndvi_imagen` | Una fila por imagen del plot, `clases` = `[{clase, color, ndvi_min, ndvi_max, percent}]` | `guardar_ndvi` |
| `ambiente_diario` | Derivada: `meteo_diaria` + `resumir_phytech` + `ndvi_diario` + `construir_ambiente_diario` por día cerrado | `ambiente_service.recalcular(db, fundo, fechas)` |
| `riego_registro` / `riego_ciclo` | Un registro versionado por turno-día con hash de contenido (`riego_contenido.hash_contenido`) | carga histórica (y Excel en F2) |

- **Conversión de WeatherLink**: `app/integraciones/weatherlink/conversion.py` es el único lugar
  con las reglas de H7 (tabla `REGLAS` documentada: T° Prom = T° Máx = `temp_out_hi`, ETo =
  `et`×25,4, viento = `wind_run`×1,609344, DPV por Tetens con `temp_out`…). `lecturas_saneadas`
  devuelve lo que va a `meteo_lectura`. **Corte de día** (`MEDIANOCHE_AL_DIA_QUE_TERMINA`): el
  registro con `ts` local 00:00 cierra el día anterior y se guarda como `D 00:00` del día que
  termina, como hace el Excel desde el 13-sep-2021 (antes lo ponía en el día nuevo); cada día local
  tiene los registros con `ts` en `(D 00:00, D+1 00:00]`. Coincidencia medida contra
  `data_metereologica.xlsx` (nov-2021, 1440 registros): 100 % en todas las columnas, también la
  lectura de medianoche; y el clima diario armado desde la BD con un mes de WeatherLink empalmado
  con el Excel es idéntico al del Excel (`test_paridad_historico`).
- **Mapeo de columnas** BD (minúsculas) ↔ `riego_ml`: solo en `app/ml/columnas.py`.
- **`ambiente_diario`**: solo días `< hoy_lima()`; un día con solo NDVI se escribe con banderas en
  0; un día sin datos no tiene fila (la ruta por archivos agrega días vacíos al calendario, pero
  `features_ambiente` rellena la grilla igual: mismo resultado).
- **Historial desde la BD** (`app/ml/historial_bd.construir_historial(db, modulo_id, hasta=…)`):
  riego vigente (un `sin_riego` cuenta como dato), y con `hasta`, para turno-días sin registro, los
  ciclos del cronograma de referencia de ese día (informados en `turno_dias_cronograma`);
  `limpiar_ciclos(5, 2)` → `tabla_turno_dia` → ambiente con los nombres de `riego_ml`.
- **Paridad** (`tests/test_paridad_historico.py`): con todo `ml/data/raw` cargado, el ambiente y el
  Historial de la BD coinciden con la ruta por archivos y el plan del día siguiente es idéntico;
  además, nov-2021 de `WeatherLink/completo` pasado por `conversion` y guardado (del 14 al 30,
  solapado dos días con el Excel del 1 al 15) da exactamente el mismo `meteo_diaria` que el Excel
  (T_media, T_min, HR_media, Viento_media y lecturas por día sin diferencia). El
  ambiente admite 0,001 en ≈0,1 % de los valores: `groupby().mean()` de pandas puede diferir en el
  último bit según el tamaño del DataFrame y, en un empate, cambia el `round(3)` (pasa también
  dentro de `riego_ml` con archivos de distinto rango).

### Carga histórica

```bash
DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/riego_dev \
  .venv/Scripts/python -m app.cli cargar-historico            # todas las fuentes
.venv/Scripts/python -m app.cli cargar-historico --fuentes meteo,riego --riego otra/ruta.xlsx
.venv/Scripts/python -m app.cli recalcular-ambiente --desde 2026-10-01 --hasta 2026-10-31
```

- Rutas por defecto = las de `ml/config/pipeline.yaml` (con las que se entrenó):
  `data_metereologica.xlsx`, `data_phytech.xlsx` (hojas `Suelo_horario`, `Planta_diario`),
  `phytech/completo` (`NdviImages_*_area12537.xlsx`, plot 70208) y `data_riego_historico.xlsx`
  (hoja MOD5). `--meteo/--phytech/--ndvi/--riego` las cambian.
- Riego: `leer_riego` + `limpiar_ciclos(5 min, 2 m3/ha)` → un `riego_registro` **aplicado** origen
  `historico` por turno-día (solo fechas < hoy). Mismo hash → se omite; distinto → conflicto
  informado (la corrida queda `parcial`), o versión nueva con `--reemplazar`.
- Sensores con `ON CONFLICT … DO UPDATE … WHERE` algo cambió. **Repetirla no inserta ni cambia
  nada.** Cada fuente queda en `ingesta_corrida` (`historico_<fuente>`, disparo `script`) y corre
  en un SAVEPOINT (una fuente con error no deshace las demás; el comando termina con código 1).
- Resultado en `riego_dev` (2026-11-08): meteo 101 195 lecturas, suelo 62 724 horas, planta 1 712
  días, NDVI 49 imágenes, riego 9 788 turno-días (115 ciclos descartados por `limpiar_ciclos`),
  `ambiente_diario` 2 128 días (2021-01-01 a 2026-11-01). Segunda corrida: 0 nuevas, 0
  actualizadas. Tarda ~3 min, casi todo en leer los Excel con openpyxl.

## Ingesta de APIs, frescura y series (F2)

Código: `integraciones/` (clientes), `services/ingesta_service.py`, `repositories/ingestas.py`,
`api/v1/endpoints/ingestas.py`; frescura y series en `services/datos_service.py`,
`repositories/datos_series.py`, `api/v1/endpoints/datos.py`; esquemas en `schemas/datos.py`.

| Método y ruta | Quién | Respuesta |
|---|---|---|
| `POST /ingestas/ejecutar` `{fuentes?, desde?, hasta?}` | A E | 202 con las corridas `en_curso` («Actualizar ahora»); 409 si una fuente ya está en curso (también si dos peticiones llegan a la vez: índice único parcial); 422 si el rango no cumple `2017-01-01 ≤ desde ≤ hasta < hoy` o supera 62 días |
| `GET /ingestas?limite&fuente` | A E S | Las últimas `limite` corridas (≤ 200, 20 por defecto) más todas las `en_curso`, sin duplicados y ordenadas por inicio descendente; incluyen `latido_at` (nullable), con errores `{tipo, status_code, endpoint sin query, mensaje}` |
| `GET /datos/frescura?modulo_id&fecha&dias` | todos | Por fuente: última fecha completa, `verde`/`naranja` respecto de D-1 y huecos de la ventana (`dias` ≤ 60, 7 por defecto); el riego trae detalle `por_turno` |
| `GET /datos/clima?desde&hasta&resolucion=diaria\|30min` | todos | `ambiente_diario` o `meteo_lectura` (30 min, máx. 31 días) |
| `GET /datos/suelo?…&resolucion=diaria\|horaria` · `GET /datos/planta` | todos | Resumen diario o `phytech_suelo_horario`; planta diaria con ET y lluvia de Phytech |
| `GET /datos/pronostico?desde&hasta&capturado` | todos | La última captura (o la indicada) |
| `GET /modulos/{id}/turnos` | todos | Turnos con área, válvulas y caudal reciente (mediana m3/h de los ciclos aplicados de 30 días) |

Las series van por defecto de los últimos 14 días cerrados, en las unidades del modelo. Las
fechas de frescura, series y `/riego` deben estar entre 2017-01-01 y hoy + 366 días (422 si no).

**Fuentes** (`weatherlink`, `phytech_suelo`, `phytech_planta`, `ndvi`, `pronostico`): cada una es
una corrida en `ingesta_corrida` y cada llamada deja su payload tal cual en `ingesta_crudo` con los
parámetros de negocio (nunca claves ni token). Luego se guardan las lecturas limpias y se
recalcula `ambiente_diario` de los días tocados.

- **Rango automático**: desde la última fecha guardada − 3 días (o desde el primer hueco de los
  últimos 14 días, si es anterior) hasta ayer en hora de Lima; sin datos, los últimos 7 días; tope
  de 62 días. NDVI: últimos 10 días. Pronóstico: una captura por día (`capturado_fecha` = hoy).
- **WeatherLink v2**: `api-key` en la query + `X-Api-Secret`, una llamada por día local
  (`(D 00:00, D+1 00:00]`, 24 h: de 00:30 a 24:00; un registro de otro día se descarta),
  conversión con `weatherlink/conversion.py`. No pisa una lectura `excel_historico` (salvo
  `reprocesar-weatherlink --pisar-excel`).
- **Phytech**: JWT pedido con `X-API-KEY`/`X-API-SECRET-KEY`, **solo en memoria**; se renueva a las
  23 h y, ante un 401, una vez (y se reintenta la llamada); un segundo 401 = error `credenciales`.
  Suelo en tramos de 7 días (una hora cuenta si trae alguna medición —humedad, temperatura,
  presión o zona radicular—, como en `data_phytech.xlsx`; las de relleno sin ninguna lectura quedan
  como hueco; y una hora guardada con dato no se reemplaza por un hueco), planta en tramos de 30
  y NDVI de 10 (del ZIP se guardan el
  manifest y los histogramas). Se guardan todos los projects del plot (el ambiente usa 907557).
- **Reintentos** (`integraciones/http.py`): timeouts (15 s de conexión, 60 s de lectura), 4
  intentos con espera creciente ante 429 (respeta `Retry-After`, tope 60 s), 5xx y errores de red.
  httpx queda en WARNING y con filtro de redacción (en INFO registraría la URL con la `api-key`).
- **Aislamiento**: un día o tramo con error deja la corrida `parcial` y sigue; una fuente con
  error no detiene las demás (cada una en su transacción y en un SAVEPOINT). Si falla el commit
  final de una fuente, la corrida se cierra como `error` en otra transacción.
- **Una corrida en curso por fuente**: índice único parcial `uq_ingesta_corrida_en_curso`; un
  «Actualizar ahora» o un `ingestar` que choca con otro responde 409 (`Conflicto`) y la tarea
  programada omite la fuente ocupada. Sin candados de sesión (sirve con el pooler 6543).
- **Latido**: mientras corre, cada corrida actualiza `latido_at` cada 60 s en una transacción
  aparte (la de la ingesta no toca la fila hasta cerrarla). El panel usa `latido_at` (o `inicio_at`
  si es nulo). Una corrida `en_curso` sin latido durante más de 10 min quedó sin dueño (proceso muerto, deploy) y se cierra como `error` («interrumpida»).
- **Tarea diaria** a `INGESTA_HORA` (05:00 Lima) en `python -m app.jobs` (o dentro de la API con
  `SCHEDULER_ENABLED=true`). Exclusión entre procesos con la fila `uq(fuente, fecha_programada)`
  (`INSERT … ON CONFLICT`, sin candados de sesión). Si el proceso arranca después de esa hora la
  lanza una vez: lo ya hecho hoy se omite y lo que terminó en `error` se repite.
- **Vigilante** (`vigilar_ingestas`, cada 5 min): cierra las corridas sin latido y, pasada
  `INGESTA_HORA`, ejecuta las programadas de hoy interrumpidas o que faltan (p. ej. se omitieron
  por un «Actualizar ahora» en curso). Un error de la API no se repite ahí.

```bash
# Siempre contra la base local: backend/.env apunta a producción.
export DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/riego_dev
export DATABASE_URL_MIGRACIONES=$DATABASE_URL
.venv/Scripts/python -m app.cli ingestar                       # rango automático, todas las fuentes
.venv/Scripts/python -m app.cli ingestar --fuentes weatherlink,phytech_suelo --desde 2026-11-05 --hasta 2026-11-07
# Cambió una regla de conversion.py: re-deriva meteo_lectura (origen weatherlink) desde los
# payloads guardados, sin descargar, y recalcula ambiente_diario. Lee también los payloads del
# día anterior y del siguiente (el de las 24:00 puede estar en el del día siguiente) y borra las
# etiquetas que dejó la regla anterior.
.venv/Scripts/python -m app.cli reprocesar-weatherlink --desde 2026-11-01 --hasta 2026-11-07
# Error conocido del Excel histórico (p. ej. la ETo duplicada del 31/10/2026): WeatherLink
# reemplaza también las lecturas excel_historico de esos días (máx. 31 días; auditoría
# meteo_excel_pisado con lo reemplazado por día).
.venv/Scripts/python -m app.cli reprocesar-weatherlink --desde 2026-10-31 --hasta 2026-10-31 --pisar-excel
```

**Probar con claves reales**: `WEATHERLINK_API_KEY/SECRET` y `PHYTECH_API_KEY/SECRET` se leen de
`backend/.env`; exporta la `DATABASE_URL` local como arriba y pide rangos chicos (las APIs se usan
solo para leer). La suite de pruebas nunca usa claves reales: `tests/conftest.py` las deja vacías
y los clientes se prueban con `httpx.MockTransport` (`tests/apis_falsas.py`).

Prueba real en `riego_dev` (2026-11-08, del 05 al 07/11): WeatherLink 144 lecturas (3 llamadas),
Phytech suelo 144 horas (2 projects del plot), planta 3 días, NDVI 0 imágenes (no hubo en esos
días) y pronóstico 20 filas; al repetirla, 0 nuevas. La ETo diaria de WeatherLink coincide con la
ET de Phytech (4,37/4,32, 3,65/3,61 y 4,95/4,90 mm). Suelo y planta de la API para el 27–29/10
son idénticos a los del Excel histórico (planta solo agrega ET y lluvia). WeatherLink del
30/10 al 01/11 contra `data_metereologica.xlsx` (144 registros): Rad y Lluvia 100 %; T, T_max,
T_min, HR, DPV y Viento ≈ 98 %: la única diferencia era el registro que cierra a medianoche, que el
Excel guarda como «00:00» del día que termina (con el corte de día actual coinciden al 100 %); ETo
84 % porque el 31/10 el Excel trae duplicada la ETo de las horas en punto.

Corrección en `riego_dev` (2026-11-08, revisión de F2): `reprocesar-weatherlink` del 30/10 al 07/11
con el corte nuevo (5 lecturas actualizadas, 2 etiquetas viejas borradas; el 03/11 la T_min pasó
de 21,7 a 21,1 °C), `ingestar --fuentes weatherlink` del 04 al 07/11 (trae la lectura de las 24:00
del 07/11) y `--pisar-excel` del 31/10 (ETo 4,395 → 3,63 mm; Phytech: 3,58).

## Riego aplicado y carga de Excel (F2)

Código: `api/v1/endpoints/riego.py`, `services/riego_service.py` (consulta y versiones),
`services/carga_riego_service.py` (vista previa, marcar, confirmar, descartar, vencimiento),
`services/archivo_excel.py` (validación del archivo), `schemas/riego.py`, `repositories/riego.py`.

| Método y ruta | Quién | Respuesta |
|---|---|---|
| `GET /riego?modulo_id&desde&hasta` | todos | `{modulo_id, desde, hasta, registros}`: vigentes por turno-día con estado, origen, `sin_riego` y ciclos. Por defecto los últimos 14 días; rango máx. 366 |
| `GET /riego/{turno_id}/{fecha}/versiones` | A E S | Todas las versiones (la 1 es el original), con `vigente` y `basado_en_id` |
| `POST /riego/registros` | A E S | 201 con la versión nueva (edición manual, «no se regó» o marcar aplicado). Aplicado solo para días pasados, u **hoy cuando terminó el último ciclo** (hora de Lima); nunca a futuro |
| `DELETE /riego/registros/{id}` `{motivo}` | A E S | Quita el riego vigente: el turno-día queda sin registro, la versión sigue en el historial (`vigente=false`) y el motivo va a la auditoría (`riego_eliminado`). 409 si ya no es el vigente |
| `POST /riego/cargas` (multipart `archivo`, `modulo_id`) | A E | 201 con la vista previa (`CargaRiegoSalida`: `resumen.contadores` por resultado y `grupos` por turno-día) |
| `GET /riego/cargas/{id}` · `PATCH …` `{grupos: [{id, aplicar}]}` | A E | La carga; PATCH marca/desmarca grupos aplicables |
| `POST /riego/cargas/{id}/confirmar` · `POST …/descartar` | A E | La carga confirmada / descartada (409 si venció) |

- **Validación del archivo** (§3.5 punto 1, antes de abrirlo con pandas): nombre `.xlsx`,
  ≤ `UPLOAD_MAX_MB` (15 MB; se rechaza por `Content-Length` y se lee con tope → 413), firma ZIP,
  ZIP legible con ≤ 1000 partes, descomprimido declarado ≤ 200 MB y relación ≤ 100 (bomba ZIP),
  cada parte `.xml`/`.rels` abierta con `defusedxml` (sin DTD, entidades ni externos: *billion
  laughs* y XXE → 422), hoja `MOD5`, las 10 columnas de `leer_riego` y ≤ 100 000 filas. Antes de
  pandas la hoja se recorre una vez en streaming (`defusedxml.iterparse`): corta al pasar las
  100 000 filas (sin leer el resto) y rechaza celdas con **fórmula sin valor guardado** (archivo
  generado por script u openpyxl y nunca abierto en Excel: pandas las leería vacías y un turno
  regado parecería «no se regó»). Si openpyxl
  no está usando `defusedxml` la carga responde 503. El archivo se procesa en memoria y no se
  guarda: solo nombre saneado (sin carpetas ni caracteres de control), sha256 y tamaño.
- **Vista previa**: `leer_riego` + `limpiar_ciclos(5 min, 2 m3/ha)` (lo mismo que la carga
  histórica y el Historial), agrupado por turno-día y comparado con el vigente por
  `riego_contenido.hash_contenido`. Resultados: `nuevo`, `igual` (no crea versión),
  `reemplaza_provisional`, `reemplaza_aplicado` (desmarcado por defecto si el vigente es `manual`),
  `sin_riego` y `error` (fecha ≥ hoy en Lima, turno desconocido, válvula que no es la del turno
  —controlador o SIGA—, inicio repetido con valores distintos, fila de otro fundo/módulo). Los
  duplicados exactos los quita `limpiar_ciclos` sin error.
- **D7**: si el archivo trae una fecha y un turno activo del módulo no tiene filas (o solo
  aperturas fallidas), el grupo es `sin_riego` («no se regó», registro con 0 ciclos); marcado
  salvo que el vigente ya sea aplicado (deducir de una ausencia es más débil que lo guardado).
- **Avisos** (desmarcado por defecto, el motivo va en `mensajes` y empieza con «Aviso:»): en la
  **última fecha del archivo** (puede venir cortada si se exportó a mitad del día) ningún
  `reemplaza_aplicado` ni `sin_riego` queda marcado; en cualquier fecha, un `reemplaza_aplicado`
  con menos ciclos o menos m3 que el vigente tampoco. `resumen` trae `ultima_fecha_archivo` y
  `desmarcados_por_aviso`. El usuario puede marcarlos si los revisó.
- **Confirmar**: bloquea la carga y los vigentes del rango (`FOR UPDATE`); si pasaron 24 h desde
  la subida o cambió algún registro comparado (otra carga o edición), la carga queda **vencida** y
  responde 409 «Sube el archivo otra vez» (excepción documentada a la unidad de trabajo: ese cambio
  de estado se confirma antes del 409). Lo marcado queda como versión nueva **aplicado** origen
  `excel` (`carga_id`, `basado_en_id` = vigente reemplazado, que pasa a `vigente = false`).
  `GET` de una carga vencida por tiempo también la marca `vencida`.
- **Auditoría** (entidad `carga_riego`, id de la carga): `excel_subido` (archivo, sha256,
  contadores, rango), `excel_confirmado` (aplicados por resultado, registros creados, versiones
  reemplazadas), `excel_descartado`.
- **Prueba con el Excel real** (`ml/data/raw/data_riego.xlsx`, 15 148 filas, 2021-04-08 a
  2025-04-24) contra `riego_dev` con la carga histórica ya hecha: vista previa en ~16 s (≈25 s
  por HTTP con la respuesta de 4,8 MB) → 7 089 igual, 3 reemplaza aplicado (2025-04-24, distinto
  en `data_riego_historico.xlsx`), 223 sin riego (222 por D7 y 1 solo con aperturas fallidas);
  confirmar en ~4 s; **resubir → 7 315 igual**. Ese 2025-04-24 venía cortado (última fecha: un
  ciclo de dos en TE03–TE05); en `riego_dev` se restauró el histórico como versión 3 y hoy la
  vista previa los muestra como `reemplaza_aplicado` desmarcados con aviso (validación 1,4 s,
  vista previa 12,6 s).

## Predicción y cronogramas (F3)

| Ruta | Quién | Qué hace |
|---|---|---|
| `POST /cronogramas/generar` | A E | `{modulo_id, fecha_inicio?, dias, regenerar_existentes}` → resultado por día (creado / regenerado / omitido), marcas y frescura |
| `GET /cronogramas?modulo_id&desde&hasta&estado` | todos | Listado por fecha (el programador solo ve los publicados) |
| `GET /cronogramas/por-fecha?modulo_id&fecha` | todos | Detalle del cronograma de ese día o `null` («Hoy y mañana») |
| `GET /cronogramas/{id}` | A E S; P publicado | Cabecera, versión vigente (borrador si hay; el programador, la publicada) con turnos y ciclos, e historial de versiones |
| `GET /cronogramas/{id}/versiones[/{n}]` | A E S; P solo publicadas | Historial o una versión completa |
| `POST /cronogramas/{id}/regenerar` | A E | `{confirmar}`: versión `regenerado`; 409 si el borrador tiene correcciones y no se confirmó |

- **Modelo** (`app/ml/model_loader.py`): se carga una vez por proceso desde `ML_MODEL_PATH`,
  comparando antes su sha256 con `ML_MODEL_SHA256` (obligatorio en producción). Se registra en
  `modelo_version` y el health muestra la versión cargada.
- **Bucle** (`app/ml/generador.py`): historial desde la BD hasta el último día de la ventana; por
  cada día que se genera, `features_para_fechas` → `plan.predecir` → se agrega al historial (igual
  que `planificar`). Los días que no se tocan entran con su riego vigente o su versión de
  referencia. Con días nuevos el resultado es idéntico a `planificar`.
- **Foto de entradas** (`prediccion_entrada`): por generación, fecha y turno, las features
  turno-día y de ciclo, el origen del riego de D-1 y `alternativas_n` (salida del modelo forzando
  n = 1..5, para cambiar el n° de ciclos en F4).
- **Reglas por día** (§3.1): sin cronograma → Borrador v1 `modelo`; Borrador sin correcciones →
  versión `regenerado`; Borrador corregido o Publicado/Visto/Corrección solicitada → se omite,
  salvo `regenerar_existentes` (queda como borrador de cambios). Fecha inicial entre hoy − 7 y
  mañana, 1 a 7 días y al menos 45 días de riego antes.
- **Marcas** (§3.3): *preliminar* (día ≥ 2, fecha inicial mañana, riego de D-1 tomado de un
  cronograma o D-1 sin ambiente completo); *datos incompletos* (clima, suelo, planta o riego
  conocido sin D-1, o huecos de riego por turno en la última semana); *regenerado*;
  *desactualizado* (al leer: riego de D-30..D-1 o ambiente de D-14..D-1 posterior a la versión).
- **Concurrencia**: candado del modelo en el proceso y `pg_try_advisory_xact_lock` por módulo
  (de transacción, compatible con el pooler) → 409 si hay otra generación del mismo módulo.
- Cada cronograma creado o regenerado queda en la auditoría (`generar` / `regenerar`) y en su
  línea de tiempo (`cronograma_evento`).

Probar en local (BD `riego_dev`, sin tocar `backend/.env`): levanta la API con `DATABASE_URL`
local, entra como admin y usa **Generar** (3 días tarda unos 10 s), o
`POST /api/v1/cronogramas/generar {"modulo_id": 1}`.

## Riego por pulsos

La lógica de la planilla «MODELO RIEGO POR PULSOS – PALTO» vive en el backend
(`app/services/calculo_pulsos.py`, sin BD). Con `parametros_pulsos.activo` del módulo, al generar:

1. El modelo predice como siempre; de su plan solo se toma el **total de m³/ha de cada turno**.
2. ETr equivalente = m³/ha × Ea / 10 → curva 1, 2 o 3 por los umbrales (modo «automático con
   respaldo»: si los pulsos de todos los turnos no caben en un bloque de 3 h, pasa a la siguiente).
3. Pulso = agua disponible × agotamiento ÷ Ea (con «agotamiento automático», el menor entre el de la
   fase y el máximo que cabe en 3 h); pulsos por bloque con el redondeo acumulado de la planilla
   («Pulso/Turno Ajustado»). Con `ajustar_pulso_al_total`, cada pulso = total ÷ n° de pulsos.
4. Horario en fila, por vueltas: ciclo 1 de TE01, TE02, …, TE05 seguidos; al terminar, los ciclos 2
   en el mismo orden, y así, sin pausa desde la primera hora de la curva (03:00 con la curva 3,
   06:00 con la 1 o la 2). Los bloques de 3 h solo deciden cuántos ciclos tiene cada turno; cada
   turno descansa mientras riegan los demás. Duración = m³/ha ÷ capacidad de riego (el factor del turno es 60 / CR, así la edición recalcula igual).

Se guarda en `cronograma_version.calculo_pulsos` (curva, bloques, pulsos por turno, avisos) y en
`prediccion_entrada.plan_modelo` los ciclos del modelo: el historial del día siguiente usa esos
ciclos para lo planificado por pulsos (cronograma sin riego, o provisional copiado de él); el riego
**aplicado** entra siempre tal cual. Con pulsos un turno puede tener hasta 12 ciclos (editor y
riego aplicado). Paridad con la planilla: `tests/test_riego_pulsos.py`.

| Ruta | Quién | Qué hace |
|---|---|---|
| `GET /modulos/{id}/parametros-pulsos` | todos | Parámetros (o los de la planilla si aún no hay fila) y lo que se calcula de ellos |
| `PUT /modulos/{id}/parametros-pulsos` | A E | Valida (curvas que suman 100 %, PMP < CC, umbral 1 < 2, fase en la tabla) y audita `actualizar_parametros_pulsos` |

La migración 0006 siembra cada módulo con los valores de la planilla (suelo arenoso, hileras de 6 m,
4 mangueras, goteros de 1,6 L/h cada 0,5 m, Ea 0,85, crecimiento de fruta, curvas 1–3) y activo.
Para volver al plan directo del modelo basta desmarcar «Repartir los m³/ha del modelo en pulsos».

## Reportes y exportaciones (F5)

| Ruta | Quién | Qué hace |
|---|---|---|
| `GET /dashboard?modulo_id` | todos | KPIs de ayer (agua aplicada m³/ha y m³, aplicado vs modelo %, MDS, ETo), estado de mañana, pronóstico de 5 días y `ultimo_riego_fecha` (`date \| null`): última fecha hasta ayer (Lima) con riego vigente del módulo, aplicado o provisional, incluido «sin riego». El programador no recibe «aplicado vs modelo» |
| `GET /datos/agua?modulo_id&desde&hasta` | todos | Por día y turno: aplicado (riego vigente), propuesto (versión publicada; A E S: si no hay, el borrador) y `modelo_*` (última versión del modelo, nunca para el programador). Por defecto 14 días hasta ayer, máximo 92 |
| `GET /cronogramas/{id}/exportar?formato=pdf\|xlsx&orden=turno\|hora` | según visibilidad | PDF (ReportLab) o Excel (openpyxl) de la versión visible; el programador exporta siempre la publicada. Audita `exportar_pdf`/`exportar_xlsx` y deja el evento `exportado` |
| `GET /exportaciones/refinamiento.csv?desde&hasta` | A | §2.4: una fila por cronograma × turno × ciclo con claves, la foto de entradas (features turno-día y de ciclo), bloques `modelo_v1_*`, `modelo_base_*`, `final_*` y `aplicado_*` (n° de ciclos, m³/ha, inicio, duración), `estado_riego`, `motivos`, `ultimo_motivo`, `n_correcciones`, marcas, `num_versiones`, `modelo_version` y al final `anulado` (True/False, como las demás marcas), `anulado_motivo`. Incluye los cronogramas anulados para reentrenamiento. Textos escapados contra inyección de fórmulas; UTF-8 con BOM. Por defecto 90 días, máximo 366. Audita `exportar_refinamiento` |

`orden` es opcional: `turno` conserva el orden de turno y ciclo; `hora` ordena por `inicio_min`
(minutos absolutos, incluido el día siguiente), luego por orden de turno y ciclo si empatan.
Ambos formatos indican «Orden: por turno» o «Orden: por hora» en la cabecera. Un valor distinto
responde 422. El evento `exportado` registra el formato y el orden; los permisos no cambian.

Las series de clima, suelo, planta y pronóstico de la pantalla Datos de campo son las de F2
(`/datos/clima|suelo|planta|pronostico`). Dependencia nueva: `reportlab==4.5.1` (en
`requirements.txt`; instalar con `pip install -r requirements.txt`).

## Correos y tareas programadas

Los correos pasan por la cola `notificacion_correo`: la acción encola (en su misma transacción) y
un proceso de tareas los envía. El correo de recuperación guarda solo el `usuario_id`; el token se
genera al enviar (en la BD su SHA-256) y el enlace es `FRONTEND_URL/restablecer#token=…`, válido
`PASSWORD_RESET_MINUTES`.

```bash
.venv/Scripts/python -m app.jobs            # proceso de tareas (producción): correos, ingesta diaria y vigilante
.venv/Scripts/python -m app.jobs --una-vez  # procesa la cola una vez y termina
```

- En desarrollo se puede correr dentro de la API con `SCHEDULER_ENABLED=true`.
- Reclama lotes con `SELECT … FOR UPDATE SKIP LOCKED` (`enviando` + `bloqueado_hasta`); si falla
  reintenta a 1, 5, 15 y 60 minutos y al quinto intento queda en `error`. Sin destinatarios
  activos: `sin_destinatarios`.
- **SMTP**: `SMTP_HOST`, `SMTP_PORT` (587 con STARTTLS o 465 con TLS), `SMTP_USER`,
  `SMTP_PASSWORD`, `SMTP_FROM`.
- **Modo archivo**: con `SMTP_HOST` vacío cada correo se guarda como `.eml` en `backend/var/correos/`
  (ignorado por git); el log solo dice «correo guardado en archivo». Ábrelo con cualquier
  cliente de correo para ver el enlace.
- Mantenimiento: a las 03:15 (Lima) se borran los intentos de ingreso de más de 30 días y las
  sesiones de refresh y enlaces de recuperación vencidos, revocados o usados hace más de 30 días.
- Ingesta diaria de las APIs a `INGESTA_HORA` (ver «Ingesta de APIs, frescura y series»).

## Flujo del cronograma (F4)

Rutas relativas a `/api/v1`. A = administrador, E = encargado, P = programador,
S = subgerente. Las mutaciones se confirman junto con los eventos, auditoría y correos
en la transacción de `DbSesion`; los servicios solo hacen `flush`.

| Método y endpoint | Quién | Qué hace / esquema |
|---|---|---|
| `POST /cronogramas/{id}/recalcular` | A E | `EdicionEntrada` → `VersionPrevia` (sin id ni número, con avisos de solape); no guarda |
| `GET /cronogramas/{id}/alternativas` | A E | Alternativas 1–5 por turno; sigue `basada_en_id` hasta la generación de la base vigente |
| `POST /cronogramas/{id}/versiones` | A E | `GuardarVersionEntrada` → `CronogramaDetalle`; nueva corrección/edición inmutable con motivo activo |
| `DELETE /cronogramas/{id}` | A E | `{motivo, lock_version}` → `{accion: eliminado\|anulado, cronograma_id, fecha, avisos}`; motivo recortado de 3–500 caracteres, 409 si la versión cambió |
| `DELETE /cronogramas/{id}/borrador` | A E | Descarta el borrador de cambios, conserva versiones y publicación; devuelve `CronogramaDetalle` |
| `POST /cronogramas/{id}/publicar` | A E | `PublicarEntrada` → `CronogramaConAvisos`; publica, notifica y actualiza los provisionales existentes del cronograma |
| `POST /cronogramas/{id}/visto` | P A | `VistoEntrada` → `CronogramaConAvisos`; confirma la publicada y crea/actualiza provisionales |
| `POST /cronogramas/{id}/vista` | P S | 204; audita cada apertura y limita el evento a uno por usuario, versión y 30 minutos |
| `POST /cronogramas/{id}/solicitar-correccion` | S A | `SolicitarCorreccionEntrada` → `CronogramaDetalle`; conserva el borrador y notifica al encargado |
| `POST /cronogramas/{id}/mantener` | A E | `MantenerEntrada` → `CronogramaDetalle`; resuelve la solicitud con comentario obligatorio |
| `GET /cronogramas/{id}/diferencias?base={n}&contra={n}` | A E S; P restringido | `DiferenciasSalida`; números de versión, campos y ciclos agregados/quitados |
| `GET /cronogramas/{id}/eventos` | A E S | Lista de `EventoSalida`, más reciente primero; usuario por username |
| `GET /cronogramas/{id}/datos-campo?dias=7` | A E S | Ambiente del fundo del módulo entre D−días y D−1; días entre 1 y 14 |
| `POST /riego/registros` | A E S | `RegistroRiegoEntrada` → `RegistroRiegoSalida` (201), nueva versión manual del turno-día |

`CronogramaDetalle` incluye `visto_version_id`, `visto_programador_at`, `visto_por`,
`correccion_solicitada_at`, `correccion_solicitada_por` y `correccion_solicitada_motivo`.
Los campos de usuario son usernames. Los ciclos exponen también `ciclo_modelo`,
`duracion_manual` y `campos_editados`.

**Edición y concurrencia.** Guardar y publicar exigen el `lock_version` actual (409 si
cambió). `basada_en_id` debe ser el borrador abierto o, en un publicado (o visto, o con
corrección solicitada) sin borrador de cambios, la versión publicada: guardar abre entonces el
borrador de cambios, que se publica con «Publicar cambios». Los turnos omitidos y
los ciclos sin cambios conservan sus valores; `campos_editados` compara contra la base
inmediata. Un cambio de `duracion_manual` también cuenta como edición. Si falta el factor
de duración, se exige duración manual. Los valores editados se redondean a 2 decimales
en m³/ha y a 1 en minutos y m³; se validan también después de redondear. Las horas HH:MM
truncan los segundos y usan minuto módulo 1440. El solape avisa sin impedir guardar.

Eliminar/anular (`DELETE /cronogramas/{id}`) exige admin o encargado y `lock_version` vigente:

- Nunca publicado (`version_publicada_id IS NULL`, `num_publicaciones = 0`): borra el cronograma,
  versiones, turnos, ciclos y eventos. Primero bloquea las versiones e inspecciona todas las FK
  reales hacia cronograma y versión, incluidas referencias ajenas entre cronogramas. Si hay
  riego histórico, correos u otra referencia externa, anula en lugar de borrar.
- Publicado alguna vez: conserva el historial y fija `anulado_at`, `anulado_por`, `anulado_motivo`.
  El evento `anulado` conserva el motivo. Solo retira los riegos **vigentes provisionales** de
  origen cronograma cuya versión pertenezca al anulado: marca `vigente=false`, sin cambiar
  versión, hash ni ciclos y sin crear un registro «sin riego». Aplicados, manuales y otros
  orígenes/cronogramas se conservan con un aviso por turno.
- Auditoría independiente `eliminar_cronograma` / `anular_cronograma`, con módulo, fecha,
  motivo y números de versión; sobrevive al borrado físico.
- Los anulados quedan fuera del listado, consulta por fecha (`null` si no hay otro), detalle y
  acciones por ID (404), Dashboard, agua y respaldo del historial del modelo. Frescura solo
  considera riego vigente. El índice único parcial libera la fecha para generar otro borrador.
  Las consultas históricas por versión se conservan para el CSV, que incluye los anulados.
- Migración `0005`: las cascadas internas permiten borrar únicamente cronogramas nunca publicados;
  mantiene RLS, permisos de solo inserción y triggers de inmutabilidad. El downgrade conserva el
  valor del enum y rechaza módulos/fechas duplicados antes de modificar el esquema, sin borrar datos.

Las mutaciones bloquean el cronograma con `FOR UPDATE`. Riego bloquea el vigente y usa
además un candado transaccional por turno-día, para serializar primeras inserciones de
F4 cuando todavía no existe una fila. Los aplicados y provisionales manuales se conservan
al sincronizar; contenido idéntico no crea versión. Publicar cambios no crea provisionales
donde no había. Se agrega un solo evento de sincronización por acción, con todos los
turnos afectados (`actualizado` si alguno ya existía).

**Límite del esquema existente.** `riego_ciclo` exige inicios únicos por registro. Si una
versión del cronograma contiene dos ciclos con igual inicio, ese turno no se sincroniza,
se conserva su riego anterior y se devuelve un aviso; los demás turnos continúan.
La entrada de riego manual rechaza inicios duplicados con 422. No se cambia el esquema.

**Visto y días pasados.** Publicar cambios futuros/de hoy limpia el Visto. Para permitir
al programador comparar después de esa limpieza, diferencias verifica que la versión base
fue confirmada por ese usuario en un evento `visto_programador`, y que la comparación
termina en la publicada actual. Una publicación retrospectiva conserva el Visto histórico
(incluidos usuario, instante e id original), sin atribuir confirmación a la versión nueva,
y solo notifica al subgerente. Abrir el detalle no incrementa `lock_version` porque no
cambia el cronograma. Aplicado solo se acepta para fechas anteriores a hoy en Lima.

**Datos y correos.** Datos de campo conserva los nombres de `AmbienteDiario`, sin renombrar:
`eto_mm`, `t_media/t_min/t_max`, `hr_media/hr_min/hr_max`, `lluvia_mm`, `hum_*`,
`mds_contraccion_um`, `crecimiento_tronco_um`, `estres_planta_ps`, las demás mediciones y
banderas disponibles, `fundo_id` y `fecha`; omite id interno y marcas de persistencia.
Las cinco plantillas HTML/texto son `cronograma_publicado`, `cronograma_modificado`,
`cronograma_visto`, `correccion_solicitada` y `correccion_mantenida`. Resuelven destinatarios
por rol al enviar, enlazan a `FRONTEND_URL/cronogramas/{id}` y muestran como máximo 20
cambios en el correo de modificación. La confirmación HTTP solo encola, no envía correo.

## Pruebas

```bash
.venv/Scripts/python -m pytest -q
```

`test_paridad_historico` carga todo `ml/data/raw` (≈4 min la primera vez; los Excel leídos quedan
en `backend/var/cache_pruebas` y las siguientes tardan ≈1,5 min).

Usan la base `riego_test` (`TEST_DATABASE_URL`; se crea y migra sola). En un servidor local, el
fixture crea los roles `anon` y `authenticated` (NOLOGIN) para comprobar que no reciben
privilegios. Cada test corre en una transacción que se deshace; las sesiones de la app usan
`SET LOCAL ROLE riego_app`, así que se prueban los mismos privilegios y RLS que en producción.
Los correos van a un mailer falso en memoria y el reloj se mueve con `time-machine` (bloqueos,
gracia del refresh, vencimiento de enlaces, `hoy_lima` a las 23:30).

| Archivo | Cubre |
|---|---|
| `test_migraciones`, `test_seguridad_bd`, `test_semillas`, `test_ambiente_columnas`, `test_config_bd` | Esquema, RLS, privilegios, triggers, semillas, pooler 6543, health |
| `test_auth` | Login, enumeración, límites 429, JWT, refresh rotativo y reuso, logout |
| `test_recuperacion` | Recuperar → cola → restablecer, vencimiento, reintentos, modo archivo, cambio de contraseña y primer ingreso |
| `test_usuarios` | Permisos, alta, edición, último admin, revocación inmediata, contraseña temporal |
| `test_auditoria_catalogo` | Filtros y permisos de auditoría, lista blanca, fundos y motivos |
| `test_endurecimiento` | Cabeceras, producción, redacción de logs, zona horaria, `crear-admin`, tareas |
| `test_unidad_de_trabajo` | Commit/rollback de la unidad de trabajo (endpoint y CLI), sesión compartida, servicios sin commit |
| `test_weatherlink_conversion` | Reglas de conversión, corte de día (la lectura de las 24:00 en el día que termina), payload, coincidencia con `data_metereologica.xlsx` en nov-2021 (medianoche incluida) |
| `test_ingesta` | Ingesta con APIs falsas, idempotencia, Excel protegido, errores aislados, rango a las 23:30 de Lima, una corrida en curso por fuente (carrera → 409), latido y vigilante, commit fallido, reproceso (corte anterior, `--pisar-excel`), sin claves en BD ni logs |
| `test_integraciones` | Clientes HTTP con transporte simulado: autenticación, token de Phytech (401), reintentos, rango del día, suelo con paridad de `limpiar_suelo` |
| `test_datos_endpoints` | Permisos, «Actualizar ahora», frescura, series, fechas extremas (422) y turnos |
| `test_datos_campo` | Lecturas idempotentes (la API no pisa el Excel), `ambiente_diario` = riego_ml, hoy en Lima, riego por turno-día (hash, conflicto, `--reemplazar`), Historial desde la BD y respaldo del cronograma |
| `test_riego` | Permisos por rol de `/riego` y `/riego/cargas*`, subir → marcar → confirmar → resubir (todo «igual»), reemplazos y versiones, D7, avisos (última fecha, menos riego), errores de la vista previa, vencimiento (24 h y registro cambiado), auditoría, Excel malicioso (*billion laughs*, XXE, DTD, bomba ZIP), fórmulas sin valor, filas contadas en streaming y validación del archivo |
| `test_paridad_historico` | Ida y vuelta con `ml/data/raw`: ambiente, Historial y plan idénticos a la ruta por archivos, y clima diario desde WeatherLink (nov-2021) igual al del Excel (se salta sin los archivos) |

### Respuesta al marcar la vista previa

`PATCH /riego/cargas/{id}` devuelve `{id, contadores, grupos: [{id, aplicar}]}`: los contadores
por resultado de la carga y solo la selección final de los grupos solicitados (si se repite un
id, gana el último). Los resultados y ciclos no cambian al marcar. La interfaz combina esta
respuesta con la vista previa en caché y recalcula los totales seleccionados; no descarga otra
vez los ciclos. `GET`, confirmar y descartar conservan la respuesta completa.
