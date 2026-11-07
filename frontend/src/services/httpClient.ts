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
 */
import type { ErrorValidacion, RespuestaSesion } from "./tipos";

export const API_BASE = `${(import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "")}/api/v1`;

const MENSAJE_SIN_CONEXION = "No se pudo conectar con el servidor. Revisa tu conexión e inténtalo de nuevo.";

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
  if (opciones.body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  try {
    return await fetch(construirUrl(ruta, opciones.query), {
      method: opciones.method ?? "GET",
      headers,
      body: opciones.body !== undefined ? JSON.stringify(opciones.body) : undefined,
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
  422: "Revisa los datos ingresados.",
  429: "Demasiados intentos. Espera unos minutos.",
};

function textoValidacion(errores: ErrorValidacion[]): string {
  const mensajes = errores.map((e) => {
    const campo = e.loc.filter((p) => p !== "body" && p !== "query").join(".");
    return campo ? `${campo}: ${e.msg}` : e.msg;
  });
  return mensajes.join(" · ") || MENSAJE_POR_ESTADO[422];
}

async function leerError(resp: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    const texto = await resp.text();
    detail = texto ? (JSON.parse(texto) as { detail?: unknown }).detail : undefined;
  } catch {
    detail = undefined;
  }
  if (typeof detail === "string" && detail.trim()) return new ApiError(resp.status, detail);
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
  const resp = await ejecutar("/auth/refresh", { method: "POST" }, null);
  if (resp.ok) {
    const sesion = await leerCuerpo<RespuestaSesion>(resp);
    accessToken = sesion.access_token;
    oyentes.alRenovar?.(sesion);
    return sesion;
  }
  if (resp.status === 401 || resp.status === 403) {
    accessToken = null;
    return null;
  }
  throw await leerError(resp);
}

/**
 * Pide un access token nuevo con la cookie de refresh. Llamadas simultáneas comparten la
 * misma promesa. Devuelve null si no hay sesión que recuperar.
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
      const sesion = await refrescarSesion().catch(() => null);
      nuevoToken = sesion?.access_token ?? null;
    }
    if (!nuevoToken) {
      const error = await leerError(resp);
      avisarSesionPerdida();
      throw error;
    }
    // Si el reintento vuelve a dar 401 con un token recién emitido, el 401 no es de sesión
    // (p. ej. contraseña actual incorrecta): se informa el error sin cerrar la sesión.
    resp = await ejecutar(ruta, opciones, nuevoToken);
  }

  if (!resp.ok) throw await leerError(resp);
  return leerCuerpo<T>(resp);
}

export const api = {
  get: <T>(ruta: string, query?: OpcionesSolicitud["query"], signal?: AbortSignal) =>
    solicitar<T>(ruta, { query, signal }),
  post: <T>(ruta: string, body?: unknown, opciones: Omit<OpcionesSolicitud, "method" | "body"> = {}) =>
    solicitar<T>(ruta, { ...opciones, method: "POST", body }),
  patch: <T>(ruta: string, body?: unknown) => solicitar<T>(ruta, { method: "PATCH", body }),
  delete: <T>(ruta: string) => solicitar<T>(ruta, { method: "DELETE" }),
};

/** Solo para pruebas: reinicia el estado del módulo. */
export function __reiniciarParaPruebas(): void {
  accessToken = null;
  refreshEnCurso = null;
  oyentes = {};
}
