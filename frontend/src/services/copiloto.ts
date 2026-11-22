/**
 * Copiloto agrónomo: alertas del día y sugerencias del agente (n8n).
 *
 * Contrato del backend (prefijo /api/v1; backend/app/api/v1/endpoints/copiloto.py):
 * - GET  /copiloto/resumen?modulo_id&fecha               → Resumen (A E S y el agente)
 * - GET  /copiloto/sugerencias?estado&modulo_id          → Sugerencia[] (A E S), más recientes primero
 * - POST /copiloto/sugerencias/{id}/aprobar {comentario?} → Sugerencia (A E) · 409 si ya se resolvió
 * - POST /copiloto/sugerencias/{id}/descartar {comentario} → Sugerencia (A E) · comentario obligatorio
 * - GET  /copiloto/avisos?modulo_id                      → AvisosRespuesta (A E S y el agente)
 * Solo el agente crea sugerencias y confirma avisos. Aprobar no ejecuta nada: deja constancia de que se atiende.
 */
import { api } from "./httpClient";

export type Severidad = "alta" | "media" | "info";
export type EstadoSugerencia = "pendiente" | "aprobada" | "descartada";
export type TipoSugerencia = "revisar_equipo" | "revisar_datos" | "regenerar_plan" | "ajustar_riego" | "otro";

export interface Alerta {
  codigo: string;
  severidad: Severidad;
  titulo: string;
  detalle: string;
  fecha: string | null;
  turno_codigo: string | null;
  valores: Record<string, unknown>;
}

export interface TurnoPlan {
  turno_codigo: string;
  area_ha: number | null;
  n_ciclos: number;
  m3: number | null;
  m3ha: number | null;
  inicio: string | null;
  fin: string | null;
}

export interface PlanDia {
  fecha: string;
  cronograma_id: number;
  estado: string;
  estado_texto: string;
  publicado: boolean;
  version: number | null;
  eto_dia_anterior_mm: number | null;
  eto_dia_anterior_es_pronostico: boolean | null;
  eto_pronostico_mm: number | null;
  total_m3: number | null;
  total_m3ha: number | null;
  turnos: TurnoPlan[];
}

export interface Resumen {
  modulo: { id: number; codigo: string; nombre: string; area_ha: number | null; turnos: string[] };
  fecha: string;
  generado_at: string;
  plan_hoy: PlanDia | null;
  plan_manana: PlanDia | null;
  alertas: Alerta[];
  conteo_alertas: Record<Severidad, number>;
  sugerencias_pendientes: number;
}

export interface Sugerencia {
  id: number;
  modulo_id: number;
  modulo_codigo: string | null;
  fecha: string;
  turno_codigo: string | null;
  tipo: TipoSugerencia;
  alerta_codigo: string | null;
  titulo: string;
  detalle: string | null;
  estado: EstadoSugerencia;
  propuesta_por: string;
  created_at: string;
  resuelto_por: string | null;
  resuelto_at: string | null;
  comentario_resolucion: string | null;
}

/** Aviso que n8n manda solo por Telegram (cambio de nivel del MDS, ingesta fallida, riego sin respuesta). */
export interface Aviso {
  clave: string;
  codigo: "mds_nivel" | "ingesta_fallida" | "riego_sin_respuesta";
  severidad: Severidad;
  destino: "campo" | "sistema";
  icono: string;
  titulo: string;
  detalle: string;
  fecha: string;
  enviado: boolean;
  valores: Record<string, unknown>;
}

export interface AvisosRespuesta {
  modulo: { id: number; codigo: string; nombre: string };
  generado_at: string;
  avisos: Aviso[];
}

export const claveCopiloto = {
  todo: ["copiloto"] as const,
  resumen: (moduloId: number) => ["copiloto", "resumen", moduloId] as const,
  avisos: (moduloId: number) => ["copiloto", "avisos", moduloId] as const,
  sugerencias: (moduloId: number, estado: EstadoSugerencia | "todas") => ["copiloto", "sugerencias", moduloId, estado] as const,
};

export const copilotoApi = {
  resumen(moduloId: number, signal?: AbortSignal): Promise<Resumen> {
    return api.get<Resumen>("/copiloto/resumen", { modulo_id: moduloId }, signal);
  },
  avisos(moduloId: number, signal?: AbortSignal): Promise<AvisosRespuesta> {
    return api.get<AvisosRespuesta>("/copiloto/avisos", { modulo_id: moduloId }, signal);
  },
  sugerencias(moduloId: number, estado: EstadoSugerencia | "todas", signal?: AbortSignal): Promise<Sugerencia[]> {
    const query = estado === "todas" ? { modulo_id: moduloId } : { modulo_id: moduloId, estado };
    return api.get<Sugerencia[]>("/copiloto/sugerencias", query, signal);
  },
  aprobar(id: number, comentario: string): Promise<Sugerencia> {
    return api.post<Sugerencia>(`/copiloto/sugerencias/${id}/aprobar`, { comentario: comentario || null });
  },
  descartar(id: number, comentario: string): Promise<Sugerencia> {
    return api.post<Sugerencia>(`/copiloto/sugerencias/${id}/descartar`, { comentario });
  },
};
