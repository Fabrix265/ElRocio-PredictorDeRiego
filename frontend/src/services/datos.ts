/**
 * Frescura de datos e ingestas (propuesta §3.3, §3.6 y §4 «Datos de campo, panel e ingesta»).
 *
 * Contrato con el backend (prefijo /api/v1):
 * - GET  /datos/frescura?modulo_id&fecha&dias → Frescura
 * - POST /ingestas/ejecutar {fuentes?, desde?, hasta?} → 202 IngestaCorrida[] (o {corridas})
 * - GET  /ingestas?limite                       → IngestaCorrida[] (o {items}); sin secretos
 */
import { api } from "./httpClient";

export type EstadoFrescura = "verde" | "naranja" | "informativo";
export type EstadoIngesta = "en_curso" | "ok" | "parcial" | "error";
export type DisparoIngesta = "programado" | "manual" | "script";

export interface TurnoFrescura {
  turno_id?: number;
  turno_codigo: string;
  ultima_fecha: string | null;
  huecos?: string[];
}

export interface FuenteFrescura {
  /** riego_aplicado · riego_provisional · weatherlink · phytech_suelo · phytech_planta · ndvi · pronostico */
  fuente: string;
  nombre?: string | null;
  /** Última fecha COMPLETA (AAAA-MM-DD) o null si no hay datos. */
  ultima_fecha: string | null;
  estado: EstadoFrescura;
  /** NDVI y pronóstico son informativos: no ponen el panel en naranja. */
  informativa?: boolean;
  /** Días de la ventana sin dato completo (anteriores a la última fecha). */
  huecos?: string[];
  detalle?: string | null;
  por_turno?: TurnoFrescura[] | null;
}

export interface Frescura {
  modulo_id?: number;
  fecha: string;
  /** Día de referencia (D-1 = ayer respecto de `fecha`). */
  referencia?: string;
  dias?: number;
  fuentes: FuenteFrescura[];
}

export interface ErrorIngesta {
  tipo?: string | null;
  status_code?: number | null;
  endpoint?: string | null;
  mensaje?: string | null;
}

export interface IngestaCorrida {
  id: number;
  fuente: string;
  disparo: DisparoIngesta;
  usuario?: string | null;
  fecha_programada?: string | null;
  desde?: string | null;
  hasta?: string | null;
  inicio_at: string;
  fin_at?: string | null;
  duracion_ms?: number | null;
  estado: EstadoIngesta;
  filas_nuevas: number;
  filas_actualizadas: number;
  filas_omitidas: number;
  conflictos: number;
  errores: ErrorIngesta[];
}

export interface PeticionIngesta {
  /** Sin fuentes = todas. */
  fuentes?: string[];
  desde?: string;
  hasta?: string;
}

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

function normalizarCorrida(c: IngestaCorrida & { username?: string | null }): IngestaCorrida {
  return { ...c, usuario: c.usuario ?? c.username ?? null, errores: c.errores ?? [] };
}

export const datosApi = {
  async frescura(moduloId: number, fecha: string, dias: number, signal?: AbortSignal): Promise<Frescura> {
    const resp = await api.get<Frescura>("/datos/frescura", { modulo_id: moduloId, fecha, dias }, signal);
    return { ...resp, fuentes: lista<FuenteFrescura>(resp, ["fuentes", "items"]) };
  },
};

export const ingestasApi = {
  async listar(limite = 20, signal?: AbortSignal): Promise<IngestaCorrida[]> {
    const resp = await api.get<IngestaCorrida[] | { items: IngestaCorrida[] }>("/ingestas", { limite }, signal);
    return lista<IngestaCorrida>(resp, ["items", "corridas"]).map(normalizarCorrida);
  },
  async ejecutar(peticion: PeticionIngesta = {}): Promise<IngestaCorrida[]> {
    const resp = await api.post<IngestaCorrida[] | { corridas: IngestaCorrida[] }>("/ingestas/ejecutar", peticion);
    return lista<IngestaCorrida>(resp, ["corridas", "items"]).map(normalizarCorrida);
  },
};

export const claveDatos = {
  frescura: (moduloId: number, fecha: string, dias: number) => ["datos", "frescura", moduloId, fecha, dias] as const,
  frescuraTodo: ["datos", "frescura"] as const,
  ingestas: ["ingestas"] as const,
};
