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
npm run dev          # http://localhost:5173
```

| Comando | Qué hace |
|---|---|
| `npm run dev` | Servidor de desarrollo. Vite reenvía `/api` a `http://localhost:8000` (`API_PROXY_TARGET=http://host:puerto npm run dev` para otro backend local). |
| `npm run build` | Revisión de tipos (`tsc --noEmit`) y build de producción en `dist/` (no se versiona). |
| `npm run preview` | Sirve el build para revisarlo. |
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
  components/ui/          Button, Input, PasswordInput, Field, Select, Dialog (y panel lateral),
                          DropdownMenu, Badge, Card, DataTable, Skeleton, EmptyState, PageHeader,
                          Toast, Alert, Tooltip
  services/httpClient.ts  Cliente HTTP: /api/v1, Authorization, refresh de vuelo único, errores tipados
  features/auth/          AuthProvider, RutaProtegida (guard), login, recuperar, restablecer, cambiar contraseña
  features/layout/        AppLayout, barra lateral, cabecera, selector Fundo › Módulo, menú de usuario, menú inferior
  features/catalogo/      GET /fundos y la selección de fundo y módulo (contexto + URL + preferencia local)
  features/dashboard/     Dashboard (en F1, tarjetas que se activan en fases posteriores)
  features/usuarios/      Gestión de usuarios (solo admin)
  features/auditoria/     Auditoría (admin y subgerente)
  pages/                  403, 404, carga y pantallas protegidas que llegan en otras fases
  lib/                    Fechas en hora de Lima, saneo de `next`, política de contraseña, roles, preferencias
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
  (y serializado entre pestañas con `navigator.locks`) y reintenta una sola vez. Si el refresh falla,
  la sesión se cierra y se vuelve al login con `?next=` (solo rutas relativas que empiezan con `/`
  y no con `//`). Cerrar sesión en una pestaña cierra las demás (BroadcastChannel).
- Todas las peticiones llevan `X-Requested-With: fetch`; las de `/auth/*` usan `credentials: "include"`.
- Con `debe_cambiar_password` el usuario solo puede ver "Crea tu contraseña" (o cerrar sesión).
- Errores: se muestra el `detail` en español del backend; las listas de validación (422) se
  convierten en un mensaje legible.
- Filtros de fecha de Auditoría: `desde`/`hasta` se envían como instantes ISO 8601 con zona de Lima
  (`AAAA-MM-DDT00:00:00-05:00` y `AAAA-MM-DDT23:59:59.999-05:00`).
- Usuario nuevo: el frontend valida `username` con `^[A-Za-z0-9._-]{3,50}$` y la política de
  contraseña (≥ 10 caracteres, letras y números, distinta del usuario); el backend tiene la última palabra.

## Acceso por pantalla (propuesta §4)

| Pantalla | Admin | Encargado | Subgerente | Programador | Fase |
|---|---|---|---|---|---|
| Dashboard | ✔ | ✔ | ✔ | ✔ | F1 (tarjetas vacías hasta F2–F5) |
| Generar | ✔ | ✔ | — | — | F3 |
| Cronogramas | ✔ | ✔ | ✔ | ✔ | F3–F4 |
| Riego aplicado | ✔ | ✔ | ✔ | ✔ | F2 |
| Datos de campo | ✔ | ✔ | ✔ | ✔ | F5 |
| Auditoría | ✔ | — | ✔ | — | F1 |
| Usuarios | ✔ | — | — | — | F1 |

El backend vuelve a validar cada permiso; el menú y el guard solo ordenan la interfaz.

## Pruebas

`npx vitest run` cubre: saneo de `next`, política de contraseña y esquemas de alta, guard de roles
(función y componente), menú por rol, cliente HTTP (refresh de vuelo único, fallo de refresh,
`navigator.locks`, cabeceras, errores), fechas en Lima (incluido el reloj a las 23:30), token del
fragmento y detalle antes/después de la auditoría.

## Librerías y notas de compatibilidad

React Router 7 (modo librería: `BrowserRouter` + `Routes`), TanStack Query 5, TanStack Table 8,
React Hook Form 7 + Zod 4 + @hookform/resolvers 7, Radix (dialog, dropdown-menu, select, tooltip),
sonner (notificaciones), lucide-react, date-fns (instalada para los calendarios de fases siguientes; en F1 basta `Intl`), @fontsource/ibm-plex-sans, Tailwind CSS 4 con
@tailwindcss/vite, Vitest 5. Todas compatibles con Vite 8 / React 19 / TypeScript 7; no hizo falta
ninguna alternativa. React Router 8 ya existe, pero se fijó la 7 como pide la propuesta.
El build separa las librerías en trozos (`react`, `router`, `formularios`, `datos`, `ui`) y carga
Usuarios y Auditoría bajo demanda.
