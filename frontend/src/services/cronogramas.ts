/**
 * Cronogramas (propuesta §3.1–§3.3 y §4; F3: generar, regenerar y lectura).
 *
 * Contrato del backend (prefijo /api/v1; esquemas en backend/app/schemas/cronograma.py):
 * - POST /cronogramas/generar {modulo_id, fecha_inicio?, dias, regenerar_existentes} → 200 GenerarSalida (A E)
 *        409 otra generación en curso · 422 fecha fuera de hoy−7..mañana o < 45 días de riego · 503 sin modelo
 * - GET  /cronogramas?modulo_id&desde&hasta&estado      → 200 CronogramaListado[] (P solo publicados)
 * - GET  /cronogramas/por-fecha?modulo_id&fecha         → 200 CronogramaDetalle | null
 * - GET  /cronogramas/{id}                              → 200 CronogramaDetalle (P solo publicado)
 * - GET  /cronogramas/{id}/versiones[/{n}]              → 200 VersionResumen[] | VersionDetalle
 * - POST /cronogramas/{id}/regenerar {confirmar}        → 200 GenerarSalida (A E); 409 si el borrador
 *        tiene correcciones y no se confirmó
 *
 * Minutos desde las 00:00 de la fecha del cronograma (el fin puede pasar de 1440: día siguiente).
 */
import type { Frescura } from "./datos";
import { api } from "./httpClient";

export type EstadoCronograma = "borrador" | "publicado" | "visto" | "correccion_solicitada";
export type OrigenVersion = "modelo" | "regenerado" | "correccion" | "edicion";
export type AccionDia = "creado" | "regenerado" | "omitido";

export interface ResultadoDia {
  fecha: string;
  accion: AccionDia;
  cronograma_id: number | null;
  version: number | null;
  borrador_de_cambios: boolean;
  preliminar: boolean | null;
  datos_incompletos: boolean | null;
  mensaje: string | null;
}

export interface GenerarSalida {
  generacion_id: number;
  modulo_id: number;
  fecha_inicio: string;
  dias: number;
  modelo_version: string;
  dias_resultado: ResultadoDia[];
  frescura: Frescura;
  duracion_ms: number | null;
}

export interface CicloCronograma {
  ciclo: number;
  riego_m3ha: number;
  riego_m3: number;
  duracion_min: number;
  inicio_min: number;
  fin_min: number;
  hora_inicio: string;
  hora_fin: string;
  fin_dia_siguiente: boolean;
  m3ha_p10: number | null;
  m3ha_p90: number | null;
  inicio_desde_min: number | null;
  inicio_hasta_min: number | null;
}

export interface TurnoCronograma {
  turno_id: number;
  turno_codigo: string;
  n_ciclos: number;
  n_ciclos_modelo: number | null;
  area_ha: number;
  factor_min_por_m3ha: number | null;
  caudal_m3h: number | null;
  total_m3ha: number;
  total_m3: number;
  total_min: number;
  ciclos: CicloCronograma[];
}

export interface VersionResumen {
  id: number;
  numero: number;
  origen: OrigenVersion;
  creado_at: string;
  creado_por: string | null;
  preliminar: boolean;
  datos_incompletos: boolean;
  regenerado: boolean;
  publicada_at: string | null;
  publicada_por: string | null;
  es_borrador: boolean;
  es_publicada: boolean;
  modelo_version: string | null;
  generacion_id: number | null;
  motivo_codigo: string | null;
  motivo_comentario: string | null;
}

export interface VersionDetalle extends VersionResumen {
  desactualizado: boolean;
  turnos: TurnoCronograma[];
  total_m3: number;
}

interface CronogramaCabecera {
  id: number;
  modulo_id: number;
  modulo_codigo: string;
  fecha: string;
  estado: EstadoCronograma;
  lock_version: number;
  num_publicaciones: number;
  version_publicada_id: number | null;
  borrador_version_id: number | null;
  tiene_borrador_cambios: boolean;
  actualizado_at: string;
}

export interface CronogramaListado extends CronogramaCabecera {
  version: Pick<VersionResumen, "id" | "numero" | "origen" | "creado_at" | "preliminar" | "datos_incompletos" | "regenerado"> | null;
}

export interface CronogramaDetalle extends CronogramaCabecera {
  version: VersionDetalle | null;
  versiones: VersionResumen[];
}

export interface GenerarEntrada {
  modulo_id: number;
  fecha_inicio?: string;
  dias: number;
  regenerar_existentes: boolean;
}

export const claveCronogramas = {
  todo: ["cronogramas"] as const,
  lista: (moduloId: number, desde: string, hasta: string) => ["cronogramas", "lista", moduloId, desde, hasta] as const,
  detalle: (id: number) => ["cronogramas", "detalle", id] as const,
  version: (id: number, numero: number) => ["cronogramas", "version", id, numero] as const,
  porFecha: (moduloId: number, fecha: string) => ["cronogramas", "por-fecha", moduloId, fecha] as const,
};

export const cronogramasApi = {
  generar(datos: GenerarEntrada): Promise<GenerarSalida> {
    return api.post<GenerarSalida>("/cronogramas/generar", datos);
  },
  regenerar(id: number, confirmar = false): Promise<GenerarSalida> {
    return api.post<GenerarSalida>(`/cronogramas/${id}/regenerar`, { confirmar });
  },
  listar(moduloId: number, desde: string, hasta: string, signal?: AbortSignal): Promise<CronogramaListado[]> {
    return api.get<CronogramaListado[]>("/cronogramas", { modulo_id: moduloId, desde, hasta }, signal);
  },
  detalle(id: number, signal?: AbortSignal): Promise<CronogramaDetalle> {
    return api.get<CronogramaDetalle>(`/cronogramas/${id}`, undefined, signal);
  },
  version(id: number, numero: number, signal?: AbortSignal): Promise<VersionDetalle> {
    return api.get<VersionDetalle>(`/cronogramas/${id}/versiones/${numero}`, undefined, signal);
  },
  porFecha(moduloId: number, fecha: string, signal?: AbortSignal): Promise<CronogramaDetalle | null> {
    return api.get<CronogramaDetalle | null>("/cronogramas/por-fecha", { modulo_id: moduloId, fecha }, signal);
  },
};
