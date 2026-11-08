/**
 * Riego aplicado y carga de Excel (propuesta §3.5 y §4 «Riego aplicado»).
 *
 * Contrato real del backend (prefijo /api/v1; esquemas en backend/app/schemas/riego.py):
 * - GET   /riego?modulo_id&desde&hasta                  → 200 RiegoListado (todos los roles)
 * - GET   /riego/{turno_id}/{fecha}/versiones           → 200 VersionRiego[] (A E S)
 * - POST  /riego/cargas  multipart {archivo, modulo_id}  → 201 CargaRiego (A E)
 *         413 archivo grande · 422 archivo inválido (detail en texto) · 503 sin defusedxml
 * - GET   /riego/cargas/{id}                             → 200 CargaRiego (A E)
 * - PATCH /riego/cargas/{id}  {grupos: [{id, aplicar}]}  → 200 CargaRiego (A E)
 * - POST  /riego/cargas/{id}/confirmar                   → 200 CargaRiego confirmada (A E)
 * - POST  /riego/cargas/{id}/descartar                   → 200 CargaRiego descartada (A E)
 *   409 en PATCH/confirmar/descartar: carga vencida (24 h o cambió un registro comparado),
 *   ya confirmada o ya descartada (detail en texto); 404 si la carga no existe.
 *
 * Las fechas de riego son días de calendario "AAAA-MM-DD"; los instantes (`*_at`), ISO 8601 con zona.
 * Los usuarios llegan por su username.
 */
import { api } from "./httpClient";

export type EstadoRiego = "provisional" | "aplicado";
export type OrigenRiego = "historico" | "cronograma" | "excel" | "manual" | "controlador";
export type EstadoCarga = "previsualizada" | "confirmada" | "descartada" | "vencida";
export type ResultadoCarga =
  | "nuevo"
  | "igual"
  | "reemplaza_provisional"
  | "reemplaza_aplicado"
  | "sin_riego"
  | "error";

/** Ciclo de riego (minutos desde las 00:00 del día del registro; fin puede superar 1440). `CicloRiegoSalida`. */
export interface CicloRiego {
  inicio_min: number;
  fin_min: number;
  duracion_min: number;
  riego_m3: number | null;
  riego_m3ha: number | null;
  area_ha?: number | null;
  valvula?: string | null;
  hora_inicio: string;
  hora_fin: string;
  fin_dia_siguiente: boolean;
}

/** Registro (versión) de un turno-día. `RegistroRiegoSalida`. */
export interface RegistroRiego {
  id: number;
  turno_id: number;
  turno_codigo: string | null;
  fecha: string;
  version: number;
  estado: EstadoRiego;
  origen: OrigenRiego;
  sin_riego: boolean;
  motivo: string | null;
  comentario: string | null;
  carga_id: number | null;
  creado_at: string | null;
  creado_por: string | null;
  ciclos: CicloRiego[];
}

/** Versión del historial de un turno-día (incluye las no vigentes). `VersionRiegoSalida`. */
export interface VersionRiego extends RegistroRiego {
  vigente: boolean;
  basado_en_id: number | null;
}

/** `RiegoListado`: registros vigentes del módulo en el rango (hasta inclusivo). */
export interface RespuestaRiego {
  modulo_id: number;
  desde: string;
  hasta: string;
  registros: RegistroRiego[];
}

/** Grupo turno-día de una carga (vista previa). `GrupoCargaSalida`. */
export interface GrupoCarga {
  id: number;
  fecha: string;
  turno_id: number | null;
  turno_codigo: string | null;
  resultado: ResultadoCarga;
  aplicar: boolean;
  vigente_id_comparado?: number | null;
  /** Estado y origen del registro vigente que se reemplazaría (si lo hay). */
  vigente_estado?: EstadoRiego | null;
  vigente_origen?: OrigenRiego | null;
  ciclos: CicloRiego[];
  mensajes: string[];
}

/** `CargaRiegoSalida`. */
export interface CargaRiego {
  id: number;
  modulo_id: number;
  archivo_nombre: string;
  sha256: string;
  tamano_bytes: number;
  subido_at: string;
  subido_por: string | null;
  estado: EstadoCarga;
  /** Instante en que vence la vista previa (24 h después de subirla). */
  vence_at: string;
  confirmado_at: string | null;
  confirmado_por: string | null;
  resumen: Record<string, unknown> | null;
  grupos: GrupoCarga[];
}

/** `CambioAplicar` (cuerpo del PATCH: `{grupos: CambioAplicar[]}`, al menos uno). */
export interface CambioAplicar {
  id: number;
  aplicar: boolean;
}

// ---------------------------------------------------------------------------
// Normalización: fechas a "AAAA-MM-DD" y ciclos ordenados por inicio
// ---------------------------------------------------------------------------

export function normalizarRegistro<T extends RegistroRiego>(r: T): T {
  return { ...r, fecha: r.fecha.slice(0, 10), ciclos: [...(r.ciclos ?? [])].sort((a, b) => a.inicio_min - b.inicio_min) };
}

export function normalizarCarga(c: CargaRiego): CargaRiego {
  const grupos = (c.grupos ?? []).map((g) => ({
    ...g,
    fecha: g.fecha.slice(0, 10),
    ciclos: [...(g.ciclos ?? [])].sort((a, b) => a.inicio_min - b.inicio_min),
    mensajes: g.mensajes ?? [],
  }));
  return { ...c, grupos };
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export const riegoApi = {
  async listar(moduloId: number, desde: string, hasta: string, signal?: AbortSignal): Promise<RegistroRiego[]> {
    const resp = await api.get<RespuestaRiego>("/riego", { modulo_id: moduloId, desde, hasta }, signal);
    return resp.registros.map(normalizarRegistro);
  },
  async versiones(turnoId: number, fecha: string, signal?: AbortSignal): Promise<VersionRiego[]> {
    const resp = await api.get<VersionRiego[]>(`/riego/${turnoId}/${fecha}/versiones`, undefined, signal);
    return resp.map(normalizarRegistro).sort((a, b) => b.version - a.version);
  },
  async subirCarga(moduloId: number, archivo: File): Promise<CargaRiego> {
    const formulario = new FormData();
    formulario.append("modulo_id", String(moduloId));
    formulario.append("archivo", archivo, archivo.name);
    return normalizarCarga(await api.postFormulario<CargaRiego>("/riego/cargas", formulario));
  },
  async carga(id: number, signal?: AbortSignal): Promise<CargaRiego> {
    return normalizarCarga(await api.get<CargaRiego>(`/riego/cargas/${id}`, undefined, signal));
  },
  async marcar(id: number, grupos: CambioAplicar[]): Promise<CargaRiego> {
    return normalizarCarga(await api.patch<CargaRiego>(`/riego/cargas/${id}`, { grupos }));
  },
  async confirmar(id: number): Promise<CargaRiego> {
    return normalizarCarga(await api.post<CargaRiego>(`/riego/cargas/${id}/confirmar`));
  },
  async descartar(id: number): Promise<CargaRiego> {
    return normalizarCarga(await api.post<CargaRiego>(`/riego/cargas/${id}/descartar`));
  },
};

export const claveRiego = {
  todo: ["riego"] as const,
  lista: (moduloId: number, desde: string, hasta: string) => ["riego", "lista", moduloId, desde, hasta] as const,
  versiones: (turnoId: number, fecha: string) => ["riego", "versiones", turnoId, fecha] as const,
  carga: (id: number) => ["riego", "carga", id] as const,
};
