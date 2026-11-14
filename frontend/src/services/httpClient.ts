/**
 * Cliente HTTP de la API (`/api/v1`).
 *
 * - El access token vive solo en memoria (nunca en localStorage).
 * - Ante un 401 intenta UN refresh de vuelo único: todas las peticiones que fallen a la vez
 *   comparten la misma promesa, y entre pestañas se serializa con `navigator.locks`
 *   (si el navegador no lo tiene, el backend da 30 s de gracia al token reemplazado).
 * - El refresh token va en la cookie HttpOnly `rt` (Path=/api/v1/auth), por eso las rutas
 *   de auth usan `credentials: "include"`.
 * - Todas las peticiones llevan `X-Requested-With: fetch` (el backend lo exige en refresh/logout).
 * - La sesión local solo se cierra si el backend RECHAZA el refresh (401/403). Un corte de red,
 *   un timeout o un 5xx del proxy/pooler no cierran la sesión: el error se informa y la cookie
 *   sigue sirviendo para el siguiente intento.
 */
import type { ErrorValidacion, RespuestaSesion } from "./tipos";

export const API_BASE = `${(import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "")}/api/v1`;

export const MENSAJE_SIN_CONEXION = "No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.";

/** Tiempo máximo del refresh: si el proxy o el pooler no responden, se libera el candado. */
export const TIEMPO_LIMITE_REFRESH_MS = 15_000;

export class ApiError extends Error {
  /** Código HTTP; 0 si no hubo respuesta (sin conexión). */
  readonly status: number;
  /** Mensaje en español listo para mostrar. */
  readonly detail: string;
  /** Errores de validación por campo (422), si los hay. */
  readonly errores: ErrorValidacion[];

  constructor(status: number, detail: string, errores: ErrorValidacion[] = []) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.errores = errores;
  }
}

export function mensajeDeError(error: unknown): string {
  if (error instanceof ApiError) return error.detail;
  if (error instanceof Error && error.name !== "AbortError") return error.message;
  return "Ocurrió un error inesperado.";
}

/** true si el error es transitorio (sin respuesta, timeout o error del servidor/proxy). */
export function esErrorTransitorio(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 0 || error.status >= 500);
}

type ValorQuery = string | number | boolean | null | undefined;

export interface OpcionesSolicitud {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  query?: Record<string, ValorQuery>;
  signal?: AbortSignal;
  /** Si es false no se envía Authorization ni se intenta refresh (login, recuperar…). */
  autenticado?: boolean;
  /** Envía Authorization si hay token, pero no intenta refresh ante un 401 (logout). */
  sinReintento?: boolean;
  /** Devuelve la Response sin leer el cuerpo (descarga de archivos). */
  crudo?: boolean;
}

// ---------------------------------------------------------------------------
// Estado de sesión en memoria
// ---------------------------------------------------------------------------

let accessToken: string | null = null;

export function obtenerAccessToken(): string | null {
  return accessToken;
}

export function fijarAccessToken(token: string | null): void {
  accessToken = token;
}

interface OyentesSesion {
  /** Se llama cada vez que un refresh entrega una sesión nueva. */
  alRenovar?: (sesion: RespuestaSesion) => void;
  /** Se llama cuando la sesión ya no se puede recuperar (refresh rechazado o cierre en otra pestaña). */
  alPerder?: () => void;
}

let oyentes: OyentesSesion = {};

const CANAL = "riego-sesion";
let canal: BroadcastChannel | null = null;

function obtenerCanal(): BroadcastChannel | null {
  if (canal || typeof BroadcastChannel === "undefined") return canal;
  canal = new BroadcastChannel(CANAL);
  return canal;
}

export function registrarOyentesSesion(nuevos: OyentesSesion): () => void {
  oyentes = nuevos;
  const bc = obtenerCanal();
  const alMensaje = (evento: MessageEvent) => {
    if (evento.data?.tipo === "logout") {
      accessToken = null;
      oyentes.alPerder?.();
    }
  };
  bc?.addEventListener("message", alMensaje);
  return () => {
    bc?.removeEventListener("message", alMensaje);
    if (oyentes === nuevos) oyentes = {};
  };
}

/** Avisa a las otras pestañas que se cerró la sesión. */
export function difundirCierreSesion(): void {
  obtenerCanal()?.postMessage({ tipo: "logout" });
}

function avisarSesionPerdida(): void {
  accessToken = null;
  oyentes.alPerder?.();
}

// ---------------------------------------------------------------------------
// Transporte
// ---------------------------------------------------------------------------

function construirUrl(ruta: string, query?: Record<string, ValorQuery>): string {
  let url = `${API_BASE}${ruta}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [clave, valor] of Object.entries(query)) {
      if (valor === undefined || valor === null || valor === "") continue;
      params.append(clave, String(valor));
    }
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }
  return url;
}

async function ejecutar(ruta: string, opciones: OpcionesSolicitud, token: string | null): Promise<Response> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    "X-Requested-With": "fetch",
  };
  // FormData (subida de archivos): el navegador fija Content-Type con el boundary.
  const esFormulario = typeof FormData !== "undefined" && opciones.body instanceof FormData;
  if (opciones.body !== undefined && !esFormulario) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    return await fetch(construirUrl(ruta, opciones.query), {
      method: opciones.method ?? "GET",
      headers,
      body:
        opciones.body === undefined
          ? undefined
          : esFormulario
            ? (opciones.body as FormData)
            : JSON.stringify(opciones.body),
      credentials: ruta.startsWith("/auth/") ? "include" : "same-origin",
      signal: opciones.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, MENSAJE_SIN_CONEXION);
  }
}

const MENSAJE_POR_ESTADO: Record<number, string> = {
  400: "La solicitud no es válida.",
  401: "Tu sesión venció. Vuelve a iniciar sesión.",
  403: "No tienes permiso para realizar esta acción.",
  404: "No se encontró lo que buscabas.",
  409: "El registro cambió mientras lo editabas. Recarga e inténtalo de nuevo.",
  413: "El archivo supera el tamaño máximo permitido.",
  422: "Revisa los datos ingresados.",
  429: "Demasiados intentos. Espera unos minutos.",
};

/** Nombre en español de los campos que el backend puede citar en un 422. */
const ETIQUETA_CAMPO: Record<string, string> = {
  q: "Búsqueda",
  username: "Usuario",
  nombre: "Nombre",
  correo: "Correo",
  rol: "Rol",
  activo: "Estado",
  password: "Contraseña",
  password_actual: "Contraseña actual",
  password_nueva: "Nueva contraseña",
  password_temporal: "Contraseña temporal",
  identificador: "Usuario o correo",
  token: "Enlace",
  usuario_id: "Usuario",
  accion: "Acción",
  entidad: "Entidad",
  entidad_id: "Registro",
  desde: "Desde",
  hasta: "Hasta",
  page: "Página",
  page_size: "Tamaño de página",
  modulo_id: "Módulo",
  turno_id: "Turno",
  fecha: "Fecha",
  dias: "Días",
  archivo: "Archivo",
  fuentes: "Fuentes",
  grupos: "Grupos",
  aplicar: "Aplicar",
};

function textoValidacion(errores: ErrorValidacion[]): string {
  const mensajes = errores.map((e) => {
    const partes = (e.loc ?? []).filter((p) => p !== "body" && p !== "query" && p !== "path");
    const clave = partes.length ? String(partes[partes.length - 1]) : "";
    // Un campo sin traducción no se muestra con su nombre técnico: basta el mensaje.
    const etiqueta = ETIQUETA_CAMPO[clave];
    return etiqueta ? `${etiqueta}: ${e.msg}` : e.msg;
  });
  return Array.from(new Set(mensajes)).join(" · ") || MENSAJE_POR_ESTADO[422];
}

const MENSAJE_ORIGEN_RECHAZADO = "Solicitud no permitida";

/**
 * En desarrollo, el backend rechaza login/refresh/logout con 403 «Solicitud no permitida» si el
 * Origin del navegador no está en CORS_ORIGINS/FRONTEND_URL (p. ej. Vite en otro puerto).
 */
export function pistaOrigenDesarrollo(status: number, detail: string, dev: boolean = import.meta.env.DEV): string {
  if (!dev || status !== 403 || detail !== MENSAJE_ORIGEN_RECHAZADO) return detail;
  const origen = typeof window !== "undefined" ? window.location.origin : "este origen";
  return (
    `${detail}. Configuración de desarrollo: el backend no acepta el origen ${origen}; ` +
    "agrégalo a CORS_ORIGINS (o FRONTEND_URL) en backend/.env o abre el frontend en http://localhost:5173."
  );
}

async function leerError(resp: Response, ruta = ""): Promise<ApiError> {
  let detail: unknown;
  try {
    const texto = await resp.text();
    detail = texto ? (JSON.parse(texto) as { detail?: unknown }).detail : undefined;
  } catch {
    detail = undefined;
  }
  if (typeof detail === "string" && detail.trim()) {
    const texto = ruta.startsWith("/auth/") ? pistaOrigenDesarrollo(resp.status, detail) : detail;
    return new ApiError(resp.status, texto);
  }
  if (Array.isArray(detail)) {
    const errores = detail.filter(
      (e): e is ErrorValidacion => typeof e === "object" && e !== null && "msg" in e,
    );
    return new ApiError(resp.status, textoValidacion(errores), errores);
  }
  const generico =
    MENSAJE_POR_ESTADO[resp.status] ??
    (resp.status >= 500 ? "Ocurrió un error en el servidor. Inténtalo de nuevo en unos minutos." : `Error ${resp.status}`);
  return new ApiError(resp.status, generico);
}

async function leerCuerpo<T>(resp: Response): Promise<T> {
  if (resp.status === 204 || resp.status === 205) return undefined as T;
  const texto = await resp.text();
  return (texto ? JSON.parse(texto) : undefined) as T;
}

// ---------------------------------------------------------------------------
// Refresh de vuelo único
// ---------------------------------------------------------------------------

let refreshEnCurso: Promise<RespuestaSesion | null> | null = null;

async function conCandado<T>(nombre: string, fn: () => Promise<T>): Promise<T> {
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  if (locks?.request) return locks.request(nombre, fn) as Promise<T>;
  return fn();
}

async function hacerRefresh(): Promise<RespuestaSesion | null> {
  // Tiempo límite propio (no AbortSignal.timeout) para que el candado entre pestañas nunca
  // quede tomado por un refresh colgado; el corte se informa como "sin conexión" (status 0).
  const control = new AbortController();
  const temporizador = setTimeout(
    () => control.abort(new DOMException("El refresh superó el tiempo límite", "TimeoutError")),
    TIEMPO_LIMITE_REFRESH_MS,
  );
  try {
    const resp = await ejecutar("/auth/refresh", { method: "POST", signal: control.signal }, null);
    if (resp.ok) {
      let sesion: RespuestaSesion;
      try {
        sesion = await leerCuerpo<RespuestaSesion>(resp);
      } catch {
        // Cuerpo cortado o ilegible (proxy): transitorio, la cookie puede seguir vigente.
        throw new ApiError(0, MENSAJE_SIN_CONEXION);
      }
      accessToken = sesion.access_token;
      oyentes.alRenovar?.(sesion);
      return sesion;
    }
    if (resp.status === 401 || resp.status === 403) {
      if (resp.status === 403 && import.meta.env.DEV) {
        // Un Origin no permitido parece "sin sesión": se deja la pista en la consola.
        const error = await leerError(resp, "/auth/refresh");
        if (error.detail.startsWith(MENSAJE_ORIGEN_RECHAZADO)) console.warn(error.detail);
      }
      accessToken = null;
      return null;
    }
    throw await leerError(resp, "/auth/refresh");
  } catch (error) {
    // El corte por tiempo llega como DOMException (TimeoutError/AbortError): sin conexión.
    if (control.signal.aborted && !(error instanceof ApiError)) throw new ApiError(0, MENSAJE_SIN_CONEXION);
    throw error;
  } finally {
    clearTimeout(temporizador);
  }
}

/**
 * Pide un access token nuevo con la cookie de refresh. Llamadas simultáneas comparten la
 * misma promesa. Resuelve null solo si el backend rechazó la sesión (401/403); si no hubo
 * respuesta útil (red, timeout, 5xx) rechaza con un ApiError transitorio.
 */
export function refrescarSesion(): Promise<RespuestaSesion | null> {
  if (!refreshEnCurso) {
    refreshEnCurso = conCandado("riego-refresh", hacerRefresh).finally(() => {
      refreshEnCurso = null;
    });
  }
  return refreshEnCurso;
}

// ---------------------------------------------------------------------------
// API pública
// ---------------------------------------------------------------------------

export async function solicitar<T>(ruta: string, opciones: OpcionesSolicitud = {}): Promise<T> {
  const autenticado = opciones.autenticado ?? true;
  const tokenUsado = autenticado ? accessToken : null;
  let resp = await ejecutar(ruta, opciones, tokenUsado);

  if (resp.status === 401 && autenticado && !opciones.sinReintento) {
    let nuevoToken: string | null = null;
    if (accessToken && accessToken !== tokenUsado) {
      // Otra petición ya renovó la sesión mientras esta viajaba.
      nuevoToken = accessToken;
    } else {
      // Si el refresh falla por red, timeout o 5xx, el error se propaga SIN cerrar la sesión:
      // la cookie puede seguir vigente y el siguiente intento la recuperará.
      const sesion = await refrescarSesion();
      nuevoToken = sesion?.access_token ?? null;
    }
    if (!nuevoToken) {
      // El backend rechazó el refresh (401/403): la sesión ya no se puede recuperar.
      const error = await leerError(resp, ruta);
      avisarSesionPerdida();
      throw error;
    }
    // Si el reintento vuelve a dar 401 con un token recién emitido, el 401 no es de sesión
    // (p. ej. contraseña actual incorrecta): se informa el error sin cerrar la sesión.
    resp = await ejecutar(ruta, opciones, nuevoToken);
  }

  if (!resp.ok) throw await leerError(resp, ruta);
  if (opciones.crudo) return resp as unknown as T;
  return leerCuerpo<T>(resp);
}

/** Nombre de archivo de Content-Disposition (o el de respaldo). */
function nombreArchivo(resp: Response, respaldo: string): string {
  const cabecera = resp.headers.get("Content-Disposition") ?? "";
  const m = /filename="?([^";]+)"?/i.exec(cabecera);
  return m ? m[1] : respaldo;
}

/** Descarga autenticada (con renovación de sesión) y la guarda con el nombre que da el backend. */
export async function descargar(ruta: string, query?: Record<string, ValorQuery>, respaldo = "archivo"): Promise<string> {
  const resp = await solicitar<Response>(ruta, { query, crudo: true });
  const nombre = nombreArchivo(resp, respaldo);
  const url = URL.createObjectURL(await resp.blob());
  const enlace = document.createElement("a");
  enlace.href = url;
  enlace.download = nombre;
  document.body.appendChild(enlace);
  enlace.click();
  enlace.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
  return nombre;
}

export const api = {
  get: <T>(ruta: string, query?: OpcionesSolicitud["query"], signal?: AbortSignal) =>
    solicitar<T>(ruta, { query, signal }),
  post: <T>(ruta: string, body?: unknown, opciones: Omit<OpcionesSolicitud, "method" | "body"> = {}) =>
    solicitar<T>(ruta, { ...opciones, method: "POST", body }),
  patch: <T>(ruta: string, body?: unknown) => solicitar<T>(ruta, { method: "PATCH", body }),
  put: <T>(ruta: string, body?: unknown) => solicitar<T>(ruta, { method: "PUT", body }),
  /** POST multipart (subida de archivos). */
  postFormulario: <T>(ruta: string, formulario: FormData, signal?: AbortSignal) =>
    solicitar<T>(ruta, { method: "POST", body: formulario, signal }),
  delete: <T>(ruta: string, body?: unknown) => solicitar<T>(ruta, { method: "DELETE", body }),
};

/** Solo para pruebas: reinicia el estado del módulo. */
export function __reiniciarParaPruebas(): void {
  accessToken = null;
  refreshEnCurso = null;
  oyentes = {};
}
