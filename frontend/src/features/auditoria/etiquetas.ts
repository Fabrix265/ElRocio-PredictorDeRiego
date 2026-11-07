import type { TonoBadge } from "../../components/ui/Badge";
import { formatearFechaHora } from "../../lib/fechas";
import { ETIQUETA_ROL, ROLES, type Rol } from "../../lib/roles";

/** Acciones de auditoría (propuesta §5) en lenguaje de usuario. */
const ACCIONES: Record<string, string> = {
  login: "Inicio de sesión",
  login_fallido: "Intento de ingreso fallido",
  logout: "Cierre de sesión",
  recuperar_solicitado: "Recuperación solicitada",
  password_restablecido: "Contraseña restablecida",
  password_cambiado: "Contraseña cambiada",
  password_cambio_fallido: "Cambio de contraseña fallido",
  usuario_creado: "Usuario creado",
  usuario_editado: "Usuario editado",
  rol_cambiado: "Rol cambiado",
  usuario_desactivado: "Usuario desactivado",
  usuario_activado: "Usuario activado",
  password_temporal_asignado: "Contraseña temporal asignada",
  generar: "Cronograma generado",
  regenerar: "Cronograma regenerado",
  corregir: "Cronograma corregido",
  descartar_borrador: "Borrador descartado",
  publicar: "Cronograma publicado",
  publicar_cambios: "Cambios publicados",
  visto_programador: "Visto del programador",
  vista_programador: "Abierto por el programador",
  vista_subgerente: "Visto por el subgerente",
  solicitar_correccion: "Corrección solicitada",
  mantener_version: "Versión mantenida",
  exportar_pdf: "Exportado a PDF",
  exportar_xlsx: "Exportado a Excel",
  riego_editado: "Riego editado",
  riego_marcado_aplicado: "Riego marcado como aplicado",
  riego_sin_riego: "Turno marcado sin riego",
  excel_subido: "Excel de riego subido",
  excel_confirmado: "Excel de riego confirmado",
  excel_descartado: "Excel de riego descartado",
  ingesta_manual: "Ingesta manual",
  exportar_refinamiento: "Exportación para refinamiento",
};

const ENTIDADES: Record<string, string> = {
  usuario: "Usuario",
  cronograma: "Cronograma",
  riego: "Riego",
  ingesta: "Ingesta",
  exportacion: "Exportación",
};

const CAMPOS: Record<string, string> = {
  username: "Usuario",
  nombre: "Nombre",
  correo: "Correo",
  rol: "Rol",
  activo: "Activo",
  debe_cambiar_password: "Debe cambiar la contraseña",
  identificador: "Identificador",
  motivo: "Motivo",
  comentario: "Comentario",
};

/**
 * Valores internos de `detalle` traducidos por campo (los códigos nunca se muestran en crudo).
 * Un valor sin traducción se muestra humanizado ("algo_nuevo" → "Algo nuevo").
 */
const VALORES: Record<string, Record<string, string>> = {
  motivo: {
    password_incorrecta: "Contraseña incorrecta",
    usuario_inexistente: "Usuario inexistente",
    usuario_inactivo: "Usuario inactivo",
    password_actual_incorrecta: "Contraseña actual incorrecta",
  },
};

/** Campos cuyos valores son códigos internos (se humanizan si no hay traducción). */
const CAMPOS_CODIGO = new Set(Object.keys(VALORES));

function humanizar(clave: string): string {
  const texto = clave.replace(/_/g, " ").trim();
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

export const etiquetaAccion = (accion: string) => ACCIONES[accion] ?? humanizar(accion);
export const etiquetaEntidad = (entidad: string) => ENTIDADES[entidad] ?? humanizar(entidad);
export const etiquetaCampo = (campo: string) => CAMPOS[campo] ?? humanizar(campo);

export function etiquetaRol(rol: string | null | undefined): string {
  if (!rol) return "—";
  return (ROLES as readonly string[]).includes(rol) ? ETIQUETA_ROL[rol as Rol] : humanizar(rol);
}

/** Tono del chip según la naturaleza de la acción (siempre acompañado de texto). */
export function tonoAccion(accion: string): TonoBadge {
  if (accion === "login_fallido" || accion === "password_cambio_fallido") return "error";
  if (["usuario_desactivado", "rol_cambiado", "password_temporal_asignado", "recuperar_solicitado", "solicitar_correccion"].includes(accion))
    return "aviso";
  if (["usuario_creado", "usuario_activado", "publicar", "publicar_cambios", "visto_programador"].includes(accion)) return "exito";
  if (["login", "logout"].includes(accion)) return "neutro";
  return "info";
}

const ISO_FECHA_HORA = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/;

/** Valor legible para el panel de detalle. */
export function formatearValor(valor: unknown, campo?: string): string {
  if (valor === null || valor === undefined || valor === "") return "—";
  if (typeof valor === "boolean") return valor ? "Sí" : "No";
  if (typeof valor === "number") return valor.toLocaleString("es-PE");
  if (typeof valor === "string") {
    if (campo === "rol") return etiquetaRol(valor);
    if (campo && CAMPOS_CODIGO.has(campo)) return VALORES[campo][valor] ?? humanizar(valor);
    if (ISO_FECHA_HORA.test(valor)) return formatearFechaHora(valor);
    return valor;
  }
  if (Array.isArray(valor)) return valor.map((v) => formatearValor(v)).join(", ") || "—";
  return JSON.stringify(valor);
}

export interface FilaCambio {
  campo: string;
  antes: unknown;
  despues: unknown;
  cambio: boolean;
}

function esObjeto(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/**
 * Separa el `detalle` en filas antes/después (si trae `antes` y/o `despues`) y el resto de
 * claves como datos adicionales.
 */
export function analizarDetalle(detalle: Record<string, unknown> | null): {
  cambios: FilaCambio[];
  otros: Array<[string, unknown]>;
} {
  if (!detalle) return { cambios: [], otros: [] };
  const antes = esObjeto(detalle.antes) ? detalle.antes : null;
  const despues = esObjeto(detalle.despues) ? detalle.despues : null;
  const campos = Array.from(new Set([...Object.keys(antes ?? {}), ...Object.keys(despues ?? {})]));
  const cambios = campos.map((campo) => {
    const a = antes?.[campo];
    const d = despues?.[campo];
    return { campo, antes: a, despues: d, cambio: JSON.stringify(a) !== JSON.stringify(d) };
  });
  const otros = Object.entries(detalle).filter(([k]) => !((k === "antes" && antes) || (k === "despues" && despues)));
  return { cambios, otros };
}
