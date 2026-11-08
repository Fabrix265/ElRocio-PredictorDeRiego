# Frontend · Sistema de Plan de Riego

Aplicación web de Grupo El Rocío (AvoPeru y Talsa) para el plan de riego diario del módulo
EN01-MOD5. React 19 + TypeScript estricto + Vite 8. Estética **verde y blanco**, un solo tema claro.

## Requisitos

- Node 24 y npm 11.
- El backend FastAPI corriendo en `http://localhost:8000` (ver `backend/README.md`).

## Instalación y uso

```bash
cd frontend
npm install          # usa las versiones fijadas en package-lock.json
cp .env.example .env # opcional: VITE_API_URL vacío = mismo origen (proxy de Vite)
npm run dev          # http://localhost:5173 (puerto fijo)
```

### Origen permitido (importante)

El backend solo acepta login, refresh y logout desde los orígenes de `CORS_ORIGINS` (o
`FRONTEND_URL`) de `backend/.env`; por defecto `http://localhost:5173` y `http://127.0.0.1:5173`.
Desde otro origen responde **403 «Solicitud no permitida»** y el login parece roto.

- `npm run dev` y `npm run preview` usan el puerto **5173 con `strictPort`**: si está ocupado, Vite
  se detiene con un error en vez de pasar en silencio a 5174. Libera el puerto o, si de verdad
  necesitas otro, agrégalo a `CORS_ORIGINS` (p. ej. `http://localhost:5174`) y reinicia el backend.
- Abre la app con el mismo host que figura en `CORS_ORIGINS` (`localhost` y `127.0.0.1` son
  orígenes distintos; ambos están permitidos por defecto). Desde otro equipo de la red
  (`--host`), agrega `http://<ip>:5173`.
- En modo desarrollo, el mensaje de error del login explica qué origen falta, y si el refresh
  silencioso es rechazado por Origin queda un aviso en la consola del navegador.

| Comando | Qué hace |
|---|---|
| `npm run dev` | Servidor de desarrollo. Vite reenvía `/api` a `http://localhost:8000` (`API_PROXY_TARGET=http://host:puerto npm run dev` para otro backend local). |
| `npm run build` | Revisión de tipos (`tsc --noEmit`) y build de producción en `dist/` (no se versiona). |
| `npm run preview` | Sirve el build en `http://localhost:5173` (mismo puerto y proxy que `dev`) para revisarlo. |
| `npm test` / `npx vitest run` | Pruebas (Vitest + Testing Library + jsdom). |
| `npm run typecheck` | Solo revisión de tipos. |

### Variables de entorno

| Variable | Uso |
|---|---|
| `VITE_API_URL` | URL base del backend **sin** `/api/v1`. Vacía = mismo origen. En producción, la API debe estar bajo el mismo dominio que el frontend (p. ej. `app.dominio` y `api.dominio`) para que la cookie de refresh `SameSite=Strict` funcione (decisión D6). |

## Estructura

```
src/
  theme/tokens.css        Tokens de diseño (único lugar con colores, radios, sombras, tipografía)
  index.css               Tailwind 4 (@theme inline que referencia los tokens) y estilos base
  components/ui/          Button, Input, PasswordInput, Field, Select, Checkbox (con estado mixto),
                          Dialog (y panel lateral), DropdownMenu, Badge, Card, DataTable, Skeleton,
                          EmptyState, PageHeader, Toast, Alert, Tooltip
  services/httpClient.ts  Cliente HTTP: /api/v1, Authorization, refresh de vuelo único, errores tipados,
                          subida multipart (FormData)
  services/riego.ts       Tipos y llamadas de Riego aplicado y carga de Excel (contrato F2)
  services/datos.ts       Tipos y llamadas de frescura de datos e ingestas (contrato F2)
  features/auth/          AuthProvider, RutaProtegida (guard), login, recuperar, restablecer, cambiar contraseña
  features/layout/        AppLayout, barra lateral, cabecera, selector Fundo › Módulo, menú de usuario, menú inferior
  features/catalogo/      GET /fundos y la selección de fundo y módulo (contexto + URL + preferencia local)
  features/dashboard/     Dashboard: panel de frescura con «Actualizar ahora» y últimas corridas (F2);
                          KPIs, hoy/mañana y pronóstico se activan en F3–F5
  features/riego/         Riego aplicado (tabla día × turno × ciclos, panel con versiones) y asistente
                          de carga de Excel (subir → vista previa → confirmar/descartar)
  features/usuarios/      Gestión de usuarios (solo admin)
  features/auditoria/     Auditoría (admin y subgerente)
  pages/                  403, 404, carga y pantallas protegidas que llegan en otras fases
  lib/                    Fechas en hora de Lima y días de calendario, saneo de `next`, política de
                          contraseña, roles y permisos por acción, preferencias
  test/                   Configuración de Vitest y fábricas de datos de prueba
  assets/logos/           avoperu.svg y talsa.svg (placeholders: reemplázalos por los logos reales)
```

## Diseño

- **Tokens** en `src/theme/tokens.css` (paleta de la propuesta §6 + semánticos). Tailwind no trae su
  paleta por defecto: solo existen las clases de los tokens (`bg-marca`, `text-texto-2`,
  `border-borde`, `bg-ok-bg`, `text-green-700`, …). Para cambiar un color se toca solo ese archivo.
- Barra lateral blanca de 248 px (colapsable a 72 px, se recuerda en el navegador); ítem activo
  relleno `#2A7042` con texto blanco, hover `#EEF6EF`. Cabecera blanca con filete verde de 3 px.
  Login con panel en degradado `#2A7042` → `#215A36`. En celular: una columna, menú inferior y cajón.
- IBM Plex Sans (400–700, solo subconjunto latino) y cifras tabulares (`.cifras`) en tablas y KPIs.
  Íconos Lucide. Los estados siempre van con ícono y texto (no solo color).
- Fechas siempre en hora de Lima con `formatearFechaHora` / `formatearFechaLarga` (`lib/fechas.ts`).
- Logos: `src/assets/logos/avoperu.svg` y `talsa.svg` son placeholders neutros con el texto
  "Logo AvoPeru" / "Logo Talsa". Sustitúyelos por los archivos reales con el mismo nombre.

## Autenticación (contrato con el backend)

- El access token vive **solo en memoria**. Al cargar la app se intenta `POST /auth/refresh` en
  silencio (cookie HttpOnly `rt`); mientras tanto se ve un esqueleto.
- Ante un 401, el cliente hace **un único refresh compartido** por todas las peticiones en vuelo
  (y serializado entre pestañas con `navigator.locks`) y reintenta una sola vez. El refresh tiene
  un tiempo límite de 15 s, para que un proxy colgado no deje el candado tomado.
- Solo si el backend **rechaza** el refresh (401/403) la sesión se cierra y se vuelve al login con
  `?next=` (solo rutas relativas que empiezan con `/` y no con `//`). Si falla por red, timeout o
  un 5xx (proxy, pooler), el error se muestra y la sesión sigue: la cookie sirve en el siguiente
  intento, así no se pierde un formulario a medio llenar. Si eso pasa al abrir la app, se ve
  «No se pudo conectar · Reintentar» en vez del login.
- Cerrar sesión en una pestaña cierra las demás (BroadcastChannel).
- Todas las peticiones llevan `X-Requested-With: fetch`; las de `/auth/*` usan `credentials: "include"`.
- Con `debe_cambiar_password` el usuario solo puede ver "Crea tu contraseña" (o cerrar sesión).
- Errores: se muestra el `detail` en español del backend; las listas de validación (422) se
  convierten en un mensaje legible, con el nombre del campo en español (nunca el técnico).
- Filtros de fecha de Auditoría: `desde`/`hasta` se envían como instantes ISO 8601 con zona de Lima
  (`AAAA-MM-DDT00:00:00-05:00` y `AAAA-MM-DDT23:59:59.999-05:00`).
- Usuario nuevo: el mismo contrato que el backend: `username` recortado, en minúsculas y con
  `^[a-z0-9._-]{3,60}$`, y la política de contraseña (10 a 128 caracteres, letras y números,
  distinta del usuario). Los campos con límite en el backend llevan `maxLength` (búsqueda 100,
  nombre 120, correo 254). El backend tiene la última palabra.

## Acceso por pantalla (propuesta §4)

| Pantalla | Admin | Encargado | Subgerente | Programador | Fase |
|---|---|---|---|---|---|
| Dashboard | ✔ | ✔ | ✔ | ✔ (sin «Aplicado vs modelo») | F1; frescura en F2; KPIs F3–F5 |
| ↳ «Actualizar ahora» | ✔ | ✔ | — | — | F2 |
| ↳ Últimas corridas de ingesta | ✔ | ✔ | ✔ | — | F2 |
| Generar | ✔ | ✔ | — | — | F3 |
| Cronogramas | ✔ | ✔ | ✔ | ✔ | F3–F4 |
| Riego aplicado (lectura) | ✔ | ✔ | ✔ | ✔ | F2 |
| ↳ Historial de versiones de un turno-día | ✔ | ✔ | ✔ | — | F2 |
| ↳ Carga de Excel (`/riego/cargas/…`) | ✔ | ✔ | — | — | F2 |
| ↳ Editar provisional / marcar aplicado | ✔ | ✔ | ✔ | — | F4 |
| Datos de campo | ✔ | ✔ | ✔ | ✔ | F5 |
| Auditoría | ✔ | — | ✔ | — | F1 |
| Usuarios | ✔ | — | — | — | F1 |

El backend vuelve a validar cada permiso; el menú, el guard y `puede(rol, permiso)` (`lib/roles.ts`)
solo ordenan la interfaz.

## Fase 2: riego aplicado, carga de Excel y frescura

### Riego aplicado (`/riego`)

- Tabla **día × turno** (la fecha más reciente arriba) del módulo elegido en la cabecera. Cada
  turno-día muestra su estado con ícono y texto (**Aplicado**, **Provisional**, **Sin riego** o
  **Sin registro**), el total de m³/ha, los horarios de cada ciclo (luna = termina al día
  siguiente), la versión si es > 1 y el total de m³ del día.
- Filtro Desde/Hasta (por defecto los últimos 14 días, hasta hoy; máximo 92 días) y atajos 7/14/30.
- Tocar un turno-día abre un panel lateral con la tabla de ciclos (horario, duración, m³/ha, m³ y
  total) y, para admin, encargado y subgerente, el **historial de versiones** (la 1 es el original;
  la vigente resaltada, con origen, fecha, usuario y motivo).
- La tabla usa una consulta de **contenedor** (`@container`): con poco ancho (celular o barra lateral
  abierta en pantallas medianas) cada día se vuelve una tarjeta con los turnos en 2–3 columnas, sin
  scroll horizontal.

### Carga de Excel (`/riego/cargas/nueva` y `/riego/cargas/:id`, admin y encargado)

1. **Subir**: arrastrar o elegir el `.xlsx` (se valida extensión y ≤ 15 MB antes de enviar; el
   backend valida todo lo demás: firma, descompresión, hoja `MOD5`, columnas). Se envía como
   `multipart/form-data` con `archivo` y `modulo_id`.
2. **Vista previa**: contadores por resultado (nuevo, igual, reemplaza provisional, reemplaza
   aplicado, sin riego, error). Los aplicables tienen una casilla «Aplicar todos» (marcada,
   desmarcada o mixta); tocar el contador filtra el detalle. El detalle por turno-día (por defecto
   «Con cambios», 50 por página) muestra fecha, turno, resultado, ciclos, el registro vigente que se
   reemplaza y los mensajes de error, con su casilla. Lo que viene marcado o desmarcado lo decide el
   backend (p. ej. «reemplaza aplicado» de un registro manual llega desmarcado; «sin riego» llega
   marcado y se puede desmarcar, D7). Cada cambio se envía con `PATCH` y se ve al instante
   (actualización optimista; si falla, vuelve atrás y avisa).
3. **Confirmar** (con diálogo de resumen) o **Descartar**. Si la carga venció (24 h, o el backend
   responde 409 porque cambió un registro comparado) se muestra «La carga venció» con «Subir
   otra vez» y no se puede confirmar ni marcar. Los otros dos 409 del backend («La carga ya fue
   confirmada», «La carga fue descartada», p. ej. desde otra pestaña) no se toman como vencida: se
   avisa y se recarga la carga para mostrar su estado real. Una carga confirmada muestra cuántos
   turno-días quedaron aplicados y el enlace a Riego aplicado (cuya consulta se invalida).

La URL de la vista previa (`/riego/cargas/:id`) se puede recargar o compartir mientras no venza.
La respuesta del `POST` de la subida ya trae la carga completa (con el Excel real, ~4,8 MB) y se
guarda en la caché: la vista previa no la vuelve a pedir al abrirse (`staleTime` de 60 s), tampoco
con el doble montaje de `StrictMode` en desarrollo. En celular, las etiquetas largas de los
contadores («Reemplaza provisional») hacen salto de línea (`Badge` con `ajustar`).

### Frescura de datos (Dashboard)

- `GET /datos/frescura?modulo_id&fecha=<hoy Lima>&dias=7`. Por fuente: última fecha completa,
  «Al día» / «Atrasado» respecto de ayer (y cuántos días faltan), huecos intermedios de la ventana
  («Huecos: dom 01/11, mar 03/11») y, para el riego, una línea por turno **solo con lo que difiere**:
  un turno con otra última fecha que la mayoría («TE03: hasta mié 04/11») o con huecos que no
  comparten todos los turnos («TE05: falta mar 03/11»). NDVI y pronóstico son «Informativo» y no
  cuentan como atraso. Arriba, un resumen («Todo al día» o «N fuentes atrasadas · M con huecos»).
- **Actualizar ahora** (admin, encargado): `POST /ingestas/ejecutar` con `{}` (= todas las fuentes);
  muestra una barra de avance «Actualizando: N de M fuentes terminadas» consultando `GET /ingestas`
  cada 2,5 s mientras haya corridas en curso; al terminar avisa el resultado («Datos actualizados»,
  «Actualización parcial» o «La actualización falló») y vuelve a pedir la frescura. El botón queda
  en «Actualizando…» mientras haya una ingesta en curso (también si la lanzó otra persona o la
  tarea de las 05:00); un 409 del backend se avisa con su mensaje.
- **Corridas colgadas**: una corrida `en_curso` con más de 10 min desde `latido_at` (o desde
  `inicio_at` si no tiene latido) se muestra «Sin terminar», no deshabilita el botón ni mantiene
  el sondeo. Es el mismo umbral estricto del backend (`MINUTOS_SIN_LATIDO`). Una corrida larga
  con latido reciente sigue activa. `GET /ingestas` agrega todas las `en_curso` a las últimas
  20, sin duplicados, por lo que una colgada antigua sigue visible.
- **Últimas corridas** (admin, encargado, subgerente): las 6 más recientes, con las que están en
  curso siempre primero; fuente, estado, inicio, disparo (programada/manual con usuario/script),
  duración, rango, filas nuevas/actualizadas y el primer error redactado con su código HTTP. Las
  corridas de la carga histórica y del reproceso llevan nombre propio («Carga histórica: clima»,
  «Reproceso WeatherLink»…).

### Contrato con el backend (F2)

Los tipos de `src/services/riego.ts` y `src/services/datos.ts` son **los de `backend/app/schemas`**
(`riego.py` y `datos.py`), campo por campo, y se comprobaron contra el backend real con `riego_dev`.
Los servicios solo recortan las fechas a `AAAA-MM-DD` y ordenan los ciclos por inicio. Errores:
`detail` en texto (o lista de validación en 422) que se muestra tal cual en español.

| Endpoint | Quién | Respuesta y errores |
|---|---|---|
| `GET /riego?modulo_id&desde&hasta` | todos | 200 `RiegoListado` `{modulo_id, desde, hasta, registros: [RegistroRiego]}` (solo vigentes; `hasta` inclusivo) |
| `GET /riego/{turno_id}/{fecha}/versiones` | A E S | 200 lista de `VersionRiego` (registro + `vigente`, `basado_en_id`) |
| `POST /riego/cargas` multipart (`archivo`, `modulo_id`) | A E | 201 `CargaRiego`; 413 archivo > 15 MB; 422 archivo inválido (firma, hoja `MOD5`, columnas, filas); 503 si el servidor no tiene `defusedxml` |
| `GET /riego/cargas/{id}` | A E | 200 `CargaRiego` `{id, modulo_id, archivo_nombre, sha256, tamano_bytes, subido_at, subido_por, estado, vence_at, confirmado_at, confirmado_por, resumen, grupos: [{id, fecha, turno_id, turno_codigo, resultado, aplicar, vigente_id_comparado, vigente_estado, vigente_origen, ciclos, mensajes}]}`; 404 |
| `PATCH /riego/cargas/{id}` | A E | cuerpo `{grupos: [{id, aplicar}]}` (al menos uno) → 200 `{id, contadores, grupos: [{id, aplicar}]}` (solo grupos solicitados); 409 vencida; 422 grupo ajeno, «igual» o con error |
| `POST /riego/cargas/{id}/confirmar` · `/descartar` | A E | 200 `CargaRiego` confirmada o descartada; 409 vencida, ya confirmada o ya descartada; 422 si no hay nada marcado |
| `GET /datos/frescura?modulo_id&fecha&dias` | todos | 200 `{modulo_id, fecha, referencia, dias, fuentes: [{fuente, nombre, ultima_fecha, estado (verde, naranja o informativo), informativa, huecos, detalle, por_turno: [{turno_id, turno_codigo, ultima_fecha, huecos}] o null}]}` |
| `POST /ingestas/ejecutar` `{fuentes?, desde?, hasta?}` | A E | 202 lista de corridas creadas (`estado: en_curso`); 409 si una fuente ya está en curso; 422 fuente o rango inválidos |
| `GET /ingestas?limite=20&fuente` | A E S | 200 lista de `{id, fuente, disparo, usuario, fecha_programada, desde, hasta, inicio_at, latido_at, fin_at, duracion_ms, estado, filas_nuevas, filas_actualizadas, filas_omitidas, conflictos, errores: [{tipo, status_code, endpoint, mensaje}]}` (más reciente primero; incluye carga histórica y reproceso) |

Fuentes con nombre propio: `riego_aplicado`, `riego_provisional`, `weatherlink`, `phytech_suelo`,
`phytech_planta`, `ndvi`, `pronostico` y, en las corridas, `historico_meteo`, `historico_phytech`,
`historico_ndvi`, `historico_riego` y `reprocesar_weatherlink` (otras se muestran humanizadas).
La auditoría traduce las acciones y entidades de F2 (`excel_subido/confirmado/descartado`,
`meteo_excel_pisado`, `carga_riego`, `ingesta_corrida`).

El `PATCH` devuelve solo los contadores por resultado y la selección final de los grupos
solicitados. La interfaz combina esos cambios con la carga en caché, conserva ciclos y mensajes,
y recalcula los totales seleccionados. No repite el `GET` ni descarga la carga completa por clic.

## Pruebas

`npx vitest run` cubre: saneo de `next`, política de contraseña y esquemas de alta (contrato de
username igual al backend), guard de roles (función y componente), menú y KPIs por rol, cliente
HTTP (refresh de vuelo único, refresh rechazado, refresh con 502/503/red sin cerrar la sesión,
tiempo límite, `navigator.locks`, cabeceras, errores 422 en español), AuthProvider (pantalla
«No se pudo conectar» y Reintentar), acciones de Usuarios sobre la propia cuenta, fechas en Lima
(incluido el reloj a las 23:30), token del fragmento y detalle antes/después de la auditoría.

En F2 se suman: días de calendario sin corrimiento de zona; subida multipart sin `Content-Type`
JSON; permisos de la carga de Excel por rol; Riego aplicado (estados de cada turno-día, panel con
ciclos e historial para A/E/S, programador sin historial ni «Cargar Excel», atajos y validación
del rango); carga de Excel (archivo no `.xlsx` rechazado sin llamar al backend, error del backend,
contadores por resultado, «sin riego» desmarcable con actualización optimista, confirmar,
carga vencida por 409 o por 24 h, 409 «ya confirmada» que no se toma como vencida, descartar, la
vista previa que no se vuelve a pedir tras la subida); frescura (orden, atraso, huecos,
informativas, línea por turno solo con lo que difiere, programador sin botón ni corridas,
subgerente con corridas sin botón, «Actualizar ahora» con avance y sondeo hasta terminar, corrida
colgada con más de 10 min sin latido que no bloquea el botón ni deja el sondeo activo), el cálculo del avance de
las corridas, los nombres de las corridas históricas y las etiquetas de auditoría de F2.

Prueba manual de punta a punta (backend contra `riego_dev`, nunca contra el `.env` de producción):

```bash
cd backend
DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/riego_dev \
DATABASE_URL_MIGRACIONES=postgresql+psycopg://postgres@localhost:5432/riego_dev \
SCHEDULER_ENABLED=false .venv/Scripts/python -m uvicorn app.main:app --port 8766
cd frontend && API_PROXY_TARGET=http://127.0.0.1:8766 npm run dev
```

## Librerías y notas de compatibilidad

React Router 7 (modo librería: `BrowserRouter` + `Routes`), TanStack Query 5, TanStack Table 8,
React Hook Form 7 + Zod 4 + @hookform/resolvers 7, Radix (dialog, dropdown-menu, select, tooltip),
sonner (notificaciones), lucide-react, date-fns (instalada para los calendarios de fases siguientes; en F1 basta `Intl`), @fontsource/ibm-plex-sans, Tailwind CSS 4 con
@tailwindcss/vite, Vitest 5. Todas compatibles con Vite 8 / React 19 / TypeScript 7; no hizo falta
ninguna alternativa. React Router 8 ya existe, pero se fijó la 7 como pide la propuesta.
El build separa las librerías en trozos (`react`, `router`, `formularios`, `datos`, `ui`) y carga
Usuarios, Auditoría, Riego aplicado y la carga de Excel bajo demanda.
