import { urlLoginCon } from "../../lib/next";
import type { Rol } from "../../lib/roles";
import type { Usuario } from "../../services/tipos";

/** `sin_conexion`: el refresh inicial falló por red, timeout o 5xx (no se sabe si hay sesión). */
export type EstadoSesion = "cargando" | "sin_conexion" | "anonimo" | "autenticado";

export type DecisionAcceso =
  | { tipo: "cargando" }
  | { tipo: "sin_conexion" }
  | { tipo: "redirigir"; a: string }
  | { tipo: "prohibido" }
  | { tipo: "permitido" };

export const RUTA_CAMBIAR_PASSWORD = "/cambiar-password";

/**
 * Guard de rutas protegidas (función pura, probada aparte):
 * sin conexión al verificar → "Reintentar"; sin sesión → login con `next`; contraseña temporal → cambiar contraseña;
 * rol sin permiso → 403.
 */
export function decidirAcceso(params: {
  estado: EstadoSesion;
  usuario: Usuario | null;
  roles?: readonly Rol[];
  /** Ruta actual completa (pathname + search). */
  ruta: string;
  /** Tras un cierre de sesión voluntario no se guarda la ruta en `next`. */
  salidaVoluntaria?: boolean;
}): DecisionAcceso {
  const { estado, usuario, roles, ruta, salidaVoluntaria } = params;
  if (estado === "cargando") return { tipo: "cargando" };
  if (estado === "sin_conexion") return { tipo: "sin_conexion" };
  if (estado === "anonimo" || !usuario) {
    return { tipo: "redirigir", a: salidaVoluntaria ? "/login" : urlLoginCon(ruta) };
  }
  const camino = ruta.split(/[?#]/)[0];
  if (usuario.debe_cambiar_password && camino !== RUTA_CAMBIAR_PASSWORD) {
    return { tipo: "redirigir", a: RUTA_CAMBIAR_PASSWORD };
  }
  if (roles && !roles.includes(usuario.rol)) return { tipo: "prohibido" };
  return { tipo: "permitido" };
}
