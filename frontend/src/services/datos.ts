/**
 * Frescura de datos e ingestas (propuesta §3.3, §3.6 y §4 «Datos de campo, panel e ingesta»).
 *
 * Contrato real del backend (prefijo /api/v1; esquemas en backend/app/schemas/datos.py):
 * - GET  /datos/frescura?modulo_id&fecha&dias          → 200 Frescura (todos los roles; dias 1..máx)
 * - POST /ingestas/ejecutar {fuentes?, desde?, hasta?}  → 202 IngestaCorrida[] (A E)
 *        409 si alguna fuente ya está en curso · 422 fuente desconocida o fechas inválidas
 * - GET  /ingestas?limite&fuente                        → 200 IngestaCorrida[] (A E S), más recientes
 *        primero; incluye las corridas de la carga histórica y del reproceso. Sin secretos.
 */
import { api } from "./httpClient";

export type EstadoFrescura = "verde" | "naranja" | "informativo";
export type EstadoIngesta = "en_curso" | "ok" | "parcial" | "error";
export type DisparoIngesta = "programado" | "manual" | "script";

/** Fuentes que acepta `POST /ingestas/ejecutar` (sin `fuentes` = todas). */
export type FuenteIngesta = "weatherlink" | "phytech_suelo" | "phytech_planta" | "ndvi" | "pronostico";

/** `TurnoFrescura`. */
export interface TurnoFrescura {
  turno_id: number;
  turno_codigo: string;
  ultima_fecha: string | null;
  huecos: string[];
}

/** `FuenteFrescura`. */
export interface FuenteFrescura {
  /** riego_aplicado · riego_provisional · weatherlink · phytech_suelo · phytech_planta · ndvi · pronostico */
  fuente: string;
  nombre: string;
  /** Última fecha COMPLETA (AAAA-MM-DD) o null si no hay datos. */
  ultima_fecha: string | null;
  estado: EstadoFrescura;
  /** NDVI y pronóstico son informativos: no ponen el panel en naranja. */
  informativa: boolean;
  /** Días de la ventana sin dato completo (anteriores a la última fecha). */
  huecos: string[];
  detalle: string | null;
  /** Solo riego aplicado y provisional: el estado de cada turno activo. */
  por_turno: TurnoFrescura[] | null;
}

/** `FrescuraSalida`. */
export interface Frescura {
  modulo_id: number;
  fecha: string;
  /** Día de referencia (D-1 = ayer respecto de `fecha`). */
  referencia: string;
  dias: number;
  fuentes: FuenteFrescura[];
}

/** `ErrorIngestaSalida` (endpoint sin query y mensaje redactado: nunca claves ni tokens). */
export interface ErrorIngesta {
  tipo: string | null;
  status_code: number | null;
  endpoint: string | null;
  mensaje: string | null;
}

/** `IngestaCorridaSalida`. `usuario` es el username de quien la lanzó (manual). */
export interface IngestaCorrida {
  id: number;
  fuente: string;
  disparo: DisparoIngesta;
  usuario: string | null;
  fecha_programada: string | null;
  desde: string | null;
  hasta: string | null;
  inicio_at: string;
  fin_at: string | null;
  duracion_ms: number | null;
  estado: EstadoIngesta;
  filas_nuevas: number;
  filas_actualizadas: number;
  filas_omitidas: number;
  conflictos: number;
  errores: ErrorIngesta[];
}

/** `PeticionIngesta` (extra prohibido). */
export interface PeticionIngesta {
  /** Sin fuentes = todas. */
  fuentes?: FuenteIngesta[];
  desde?: string;
  hasta?: string;
}

export const datosApi = {
  frescura(moduloId: number, fecha: string, dias: number, signal?: AbortSignal): Promise<Frescura> {
    return api.get<Frescura>("/datos/frescura", { modulo_id: moduloId, fecha, dias }, signal);
  },
};

export const ingestasApi = {
  listar(limite = 20, signal?: AbortSignal): Promise<IngestaCorrida[]> {
    return api.get<IngestaCorrida[]>("/ingestas", { limite }, signal);
  },
  ejecutar(peticion: PeticionIngesta = {}): Promise<IngestaCorrida[]> {
    return api.post<IngestaCorrida[]>("/ingestas/ejecutar", peticion);
  },
};

export const claveDatos = {
  frescura: (moduloId: number, fecha: string, dias: number) => ["datos", "frescura", moduloId, fecha, dias] as const,
  frescuraTodo: ["datos", "frescura"] as const,
  ingestas: ["ingestas"] as const,
};
