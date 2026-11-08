# Backend – Sistema de Plan de Riego (Grupo El Rocío)

API FastAPI + SQLAlchemy 2 (psycopg 3) + Alembic sobre PostgreSQL (Supabase en producción).
Especificación: [`docs/propuesta_mvp.md`](../docs/propuesta_mvp.md).

```text
app/
  main.py            create_app: CORS, cabeceras de seguridad, manejo de errores, routers, lifespan
  api/deps.py        DbSesion (unidad de trabajo), usuario_actual (JWT + BD), requiere_rol(...)
  api/v1/endpoints/  health, auth, usuarios, auditoria, catalogo
  core/              config, security (argon2id, JWT), tiempo (hoy_lima), logging (redacción),
                     middleware (cabeceras), errores (mensajes en español)
  services/          auth_service, usuario_service, auditoria_service, correo_service, rate_limit,
                     lecturas_service, ambiente_service, carga_historica, riego_contenido
  repositories/      consultas SQLAlchemy (usuarios, sesiones, intentos, auditoria, correos,
                     catalogo, datos_campo, riego)
  integraciones/     weatherlink/conversion.py (°F/pulgadas/millas → °C/mm/km, tabla de reglas)
  ml/                columnas.py (mapeo BD ↔ riego_ml), historial_bd.py (BD → Historial, §2.3)
  models/ · db/      tablas del esquema riego, motor y sesiones
  emails/            plantillas Jinja2 (marca verde y blanca) y envío SMTP / archivo
  jobs/              APScheduler: cola de correos y mantenimiento (python -m app.jobs)
  cli.py             configurar-rol-app, verificar-seguridad-bd, crear-admin, cargar-historico,
                     recalcular-ambiente
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
- `GET /api/v1/health` → `{status, app, entorno, bd, rol_bd, modelo}` (503 si la BD no responde;
  `status: "degradado"` si el rol de la conexión no es `riego_app` o tiene privilegios de más).
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
  devuelve lo que va a `meteo_lectura`. Coincidencia medida contra `data_metereologica.xlsx`
  (enero 2021, 1487 registros): T_max 99,9 %, Rad 99,4 %, ETo 99,2 %, Lluvia 100 %, Viento 97,5 %,
  T/T_min/HR/DPV ≈ 96,8 % (el resto son lecturas que en el Excel vienen promediadas de otra fuente).
- **Mapeo de columnas** BD (minúsculas) ↔ `riego_ml`: solo en `app/ml/columnas.py`.
- **`ambiente_diario`**: solo días `< hoy_lima()`; un día con solo NDVI se escribe con banderas en
  0; un día sin datos no tiene fila (la ruta por archivos agrega días vacíos al calendario, pero
  `features_ambiente` rellena la grilla igual: mismo resultado).
- **Historial desde la BD** (`app/ml/historial_bd.construir_historial(db, modulo_id, hasta=…)`):
  riego vigente (un `sin_riego` cuenta como dato), y con `hasta`, para turno-días sin registro, los
  ciclos del cronograma de referencia de ese día (informados en `turno_dias_cronograma`);
  `limpiar_ciclos(5, 2)` → `tabla_turno_dia` → ambiente con los nombres de `riego_ml`.
- **Paridad** (`tests/test_paridad_historico.py`): con todo `ml/data/raw` cargado, el ambiente y el
  Historial de la BD coinciden con la ruta por archivos y el plan del día siguiente es idéntico. El
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

## Riego aplicado y carga de Excel (F2)

Código: `api/v1/endpoints/riego.py`, `services/riego_service.py` (consulta y versiones),
`services/carga_riego_service.py` (vista previa, marcar, confirmar, descartar, vencimiento),
`services/archivo_excel.py` (validación del archivo), `schemas/riego.py`, `repositories/riego.py`.

| Método y ruta | Quién | Respuesta |
|---|---|---|
| `GET /riego?modulo_id&desde&hasta` | todos | `{modulo_id, desde, hasta, registros}`: vigentes por turno-día con estado, origen, `sin_riego` y ciclos. Por defecto los últimos 14 días; rango máx. 366 |
| `GET /riego/{turno_id}/{fecha}/versiones` | A E S | Todas las versiones (la 1 es el original), con `vigente` y `basado_en_id` |
| `POST /riego/cargas` (multipart `archivo`, `modulo_id`) | A E | 201 con la vista previa (`CargaRiegoSalida`: `resumen.contadores` por resultado y `grupos` por turno-día) |
| `GET /riego/cargas/{id}` · `PATCH …` `{grupos: [{id, aplicar}]}` | A E | La carga; PATCH marca/desmarca grupos aplicables |
| `POST /riego/cargas/{id}/confirmar` · `POST …/descartar` | A E | La carga confirmada / descartada (409 si venció) |

- **Validación del archivo** (§3.5 punto 1, antes de abrirlo con pandas): nombre `.xlsx`,
  ≤ `UPLOAD_MAX_MB` (15 MB; se rechaza por `Content-Length` y se lee con tope → 413), firma ZIP,
  ZIP legible con ≤ 1000 partes, descomprimido declarado ≤ 200 MB y relación ≤ 100 (bomba ZIP),
  cada parte `.xml`/`.rels` abierta con `defusedxml` (sin DTD, entidades ni externos: *billion
  laughs* y XXE → 422), hoja `MOD5`, las 10 columnas de `leer_riego` y ≤ 100 000 filas. Si openpyxl
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
  confirmar en ~4 s; **resubir → 7 315 igual**.

## Correos y tareas programadas

Los correos pasan por la cola `notificacion_correo`: la acción encola (en su misma transacción) y
un proceso de tareas los envía. El correo de recuperación guarda solo el `usuario_id`; el token se
genera al enviar (en la BD su SHA-256) y el enlace es `FRONTEND_URL/restablecer#token=…`, válido
`PASSWORD_RESET_MINUTES`.

```bash
.venv/Scripts/python -m app.jobs            # proceso de tareas (producción): correos cada 30 s
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
| `test_weatherlink_conversion` | Reglas de conversión, 00:00 del día nuevo, payload, coincidencia con `data_metereologica.xlsx` en un mes real |
| `test_datos_campo` | Lecturas idempotentes (la API no pisa el Excel), `ambiente_diario` = riego_ml, hoy en Lima, riego por turno-día (hash, conflicto, `--reemplazar`), Historial desde la BD y respaldo del cronograma |
| `test_riego` | Permisos por rol de `/riego` y `/riego/cargas*`, subir → marcar → confirmar → resubir (todo «igual»), reemplazos y versiones, D7, errores de la vista previa, vencimiento (24 h y registro cambiado), auditoría, Excel malicioso (*billion laughs*, XXE, DTD, bomba ZIP) y validación del archivo |
| `test_paridad_historico` | Ida y vuelta con `ml/data/raw`: ambiente, Historial y plan idénticos a la ruta por archivos (se salta sin los archivos) |
