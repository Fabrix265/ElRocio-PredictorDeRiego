/**
 * Riego aplicado y carga de Excel (propuesta §3.5 y §4 «Riego aplicado»).
 *
 * Contrato con el backend (prefijo /api/v1):
 * - GET  /riego?modulo_id&desde&hasta            → RespuestaRiego (registros vigentes por turno-día)
 * - GET  /riego/{turno_id}/{fecha}/versiones     → VersionRiego[] (todas, la 1 es el original)
 * - POST /riego/cargas  (multipart: archivo, modulo_id) → CargaRiego (vista previa)
 * - GET  /riego/cargas/{id}                      → CargaRiego
 * - PATCH /riego/cargas/{id}  {grupos: [{id, aplicar}]} → CargaRiego
 * - POST /riego/cargas/{id}/confirmar            → CargaRiego (estado confirmada)
 * - POST /riego/cargas/{id}/descartar            → CargaRiego (estado descartada)
 *
 * Las fechas de riego son días de calendario "AAAA-MM-DD"; los instantes (`*_at`), ISO 8601 con zona.
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

/** Ciclo de riego (minutos desde las 00:00 del día del registro; fin puede superar 1440). */
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

/** Registro vigente de un turno-día. */
export interface RegistroRiego {
  id: number;
  turno_id: number;
  turno_codigo?: string | null;
  fecha: string;
  version: number;
  estado: EstadoRiego;
  origen: OrigenRiego;
  sin_riego: boolean;
  motivo?: string | null;
  comentario?: string | null;
  carga_id?: number | null;
  creado_at?: string | null;
  creado_por?: string | null;
  ciclos: CicloRiego[];
}

/** Versión del historial de un turno-día (incluye las no vigentes). */
export interface VersionRiego extends RegistroRiego {
  vigente: boolean;
  basado_en_id?: number | null;
}

export interface RespuestaRiego {
  modulo_id: number;
  desde: string;
  hasta: string;
  registros: RegistroRiego[];
}

/** Grupo turno-día de una carga (vista previa). */
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
  ciclos: CicloRiego[] | null;
  mensajes: string[] | null;
}

export interface CargaRiego {
  id: number;
  modulo_id: number;
  archivo_nombre: string;
  sha256?: string;
  tamano_bytes: number;
  subido_at: string;
  subido_por?: string | null;
  estado: EstadoCarga;
  /** Instante en que vence la vista previa (24 h); si falta se calcula desde `subido_at`. */
  vence_at?: string | null;
  confirmado_at?: string | null;
  confirmado_por?: string | null;
  resumen?: Record<string, unknown> | null;
  grupos: GrupoCarga[];
}

export interface CambioAplicar {
  id: number;
  aplicar: boolean;
}

// ---------------------------------------------------------------------------
// Normalización (tolera lista suelta o envoltorio {items}/{registros}/{grupos})
// ---------------------------------------------------------------------------

function lista<T>(valor: unknown, claves: string[]): T[] {
  if (Array.isArray(valor)) return valor as T[];
  if (valor && typeof valor === "object") {
    for (const clave of claves) {
      const v = (valor as Record<string, unknown>)[clave];
      if (Array.isArray(v)) return v as T[];
    }
  }
  return [];
}

export function normalizarRegistro<T extends RegistroRiego>(r: T): T {
  return { ...r, fecha: r.fecha.slice(0, 10), ciclos: [...(r.ciclos ?? [])].sort((a, b) => a.inicio_min - b.inicio_min) };
}

export function normalizarCarga(c: CargaRiego & { turnos_dia?: GrupoCarga[]; detalle?: GrupoCarga[] }): CargaRiego {
  const grupos = lista<GrupoCarga>(c, ["grupos", "turnos_dia", "detalle"]).map((g) => ({
    ...g,
    fecha: g.fecha.slice(0, 10),
    ciclos: g.ciclos ?? [],
    mensajes: g.mensajes ?? [],
  }));
  return { ...c, grupos };
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------

export const riegoApi = {
  async listar(moduloId: number, desde: string, hasta: string, signal?: AbortSignal): Promise<RegistroRiego[]> {
    const resp = await api.get<RespuestaRiego | RegistroRiego[]>("/riego", { modulo_id: moduloId, desde, hasta }, signal);
    return lista<RegistroRiego>(resp, ["registros", "items"]).map(normalizarRegistro);
  },
  async versiones(turnoId: number, fecha: string, signal?: AbortSignal): Promise<VersionRiego[]> {
    const resp = await api.get<VersionRiego[] | { versiones: VersionRiego[] }>(
      `/riego/${turnoId}/${fecha}/versiones`,
      undefined,
      signal,
    );
    return lista<VersionRiego>(resp, ["versiones", "items"])
      .map(normalizarRegistro)
      .sort((a, b) => b.version - a.version);
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
  async descartar(id: number): Promise<CargaRiego | undefined> {
    const resp = await api.post<CargaRiego | undefined>(`/riego/cargas/${id}/descartar`);
    return resp ? normalizarCarga(resp) : undefined;
  },
};

export const claveRiego = {
  todo: ["riego"] as const,
  lista: (moduloId: number, desde: string, hasta: string) => ["riego", "lista", moduloId, desde, hasta] as const,
  versiones: (turnoId: number, fecha: string) => ["riego", "versiones", turnoId, fecha] as const,
  carga: (id: number) => ["riego", "carga", id] as const,
};
