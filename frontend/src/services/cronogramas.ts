/**
 * Cronogramas (propuesta §3.1–§3.4 y §4; F3/F4: generación, lectura y flujo).
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
 * F4: recalcular, alternativas, versiones, descartar borrador, publicar, Visto, apertura,
 * solicitar corrección, mantener, diferencias, eventos, datos de campo y motivos activos.
 * Publicar/Visto devuelven el detalle con avisos; vista responde 204.
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
  ciclo_modelo: number | null;
  duracion_manual: boolean;
  campos_editados: string[];
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

/** Riego por pulsos: resumen del cálculo (backend/app/services/calculo_pulsos.py → detalle). */
export interface CalculoPulsos {
  metodo: "pulsos";
  curva: string;
  curva_propuesta: string;
  motivo: string;
  etr_equivalente_mm: number;
  ventana: [string, string] | null;
  converge: boolean;
  fase_fenologica: string;
  derivados: {
    volumen_explorado_m3ha: number;
    agua_disponible_m3ha: number;
    capacidad_riego_m3hah: number;
    agotamiento_fase: number;
    agotamiento_max_bloque: number;
    agotamiento_operativo: number;
    volumen_pulso_m3ha: number;
    minutos_pulso: number;
    intensidad_mmh: number;
  };
  bloques: {
    inicio: string; fin: string; horas: number; porcentaje: number;
    minutos_utiles: number; minutos_riego: number; reposo_min: number; converge: boolean;
  }[];
  turnos: {
    turno: string; m3ha_modelo: number; pulsos_teoricos: number[]; pulsos_por_bloque: number[];
    n_ciclos: number; m3ha_pulso: number; minutos_pulso: number; m3ha_programado: number;
  }[];
  avisos: string[];
  reglas: { ajustar_pulso_al_total: boolean; orden_turnos: string };
}

export interface VersionDetalle extends VersionResumen {
  desactualizado: boolean;
  turnos: TurnoCronograma[];
  total_m3: number;
  /** null = plan directo del modelo (módulo sin riego por pulsos). */
  calculo_pulsos?: CalculoPulsos | null;
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
  visto_version_id: number | null;
  visto_programador_at: string | null;
  visto_por: string | null;
  correccion_solicitada_at: string | null;
  correccion_solicitada_por: string | null;
  correccion_solicitada_motivo: string | null;
  /** Solo para el programador: número de su último Visto (se conserva aunque se republique). */
  mi_ultimo_visto_numero: number | null;
  version: VersionDetalle | null;
  versiones: VersionResumen[];
}

export interface GenerarEntrada {
  modulo_id: number;
  fecha_inicio?: string;
  dias: number;
  regenerar_existentes: boolean;
}

export type CicloEdicion = Pick<CicloCronograma, "ciclo" | "riego_m3ha" | "inicio_min" | "duracion_min" | "duracion_manual">;
export interface TurnoEdicion { turno_id: number; n_ciclos: number; ciclos: CicloEdicion[] }
export interface EdicionEntrada { basada_en_id: number; turnos: TurnoEdicion[] }
export interface GuardarVersionEntrada extends EdicionEntrada {
  lock_version: number;
  motivo_codigo?: string | null;
  motivo_comentario?: string | null;
}
export interface AvisoSolape { turno_id: number; ciclo: number; tipo: "solape"; mensaje: string }
export interface VersionPrevia extends Omit<VersionDetalle, "id" | "numero"> { avisos: AvisoSolape[] }
export interface CronogramaConAvisos extends CronogramaDetalle { avisos: string[] }
export interface EliminarCronogramaSalida {
  accion: "eliminado" | "anulado";
  cronograma_id: number;
  fecha: string;
  avisos: string[];
}
/** La foto del modelo no incluye los metadatos de edición de CicloSalida. */
export type CicloAlternativa = Omit<CicloCronograma, "ciclo_modelo" | "duracion_manual" | "campos_editados"> & {
  duracion_p10: number | null; duracion_p90: number | null;
};
export type Alternativas = Record<string, Record<string, CicloAlternativa[]>>;
export interface CambioVersion {
  turno_id: number; turno_codigo: string; ciclo: number | null;
  campo: string; antes: unknown; despues: unknown;
}
export interface DiferenciasSalida { base: number; contra: number; cambios: CambioVersion[] }
export interface EventoCronograma {
  tipo: string; ocurrido_at: string; usuario: string | null; version_numero: number | null;
  motivo_codigo: string | null; comentario: string | null; detalle: Record<string, unknown> | null;
}
export interface MotivoCorreccion { id: number; codigo: string; nombre: string; orden: number }
/** datos-campo conserva las columnas disponibles de AmbienteDiario. */
export type DatosCampoDia = { fecha: string; fundo_id: number } & Record<string, string | number | boolean | null>;

export const claveCronogramas = {
  todo: ["cronogramas"] as const,
  lista: (moduloId: number, desde: string, hasta: string) => ["cronogramas", "lista", moduloId, desde, hasta] as const,
  detalle: (id: number) => ["cronogramas", "detalle", id] as const,
  version: (id: number, numero: number) => ["cronogramas", "version", id, numero] as const,
  porFecha: (moduloId: number, fecha: string) => ["cronogramas", "por-fecha", moduloId, fecha] as const,
  alternativas: (id: number, base: number) => ["cronogramas", "alternativas", id, base] as const,
  diferencias: (id: number, base: number, contra: number) => ["cronogramas", "diferencias", id, base, contra] as const,
  eventos: (id: number) => ["cronogramas", "eventos", id] as const,
  datosCampo: (id: number, dias = 7) => ["cronogramas", "datos-campo", id, dias] as const,
  motivos: ["motivos-correccion"] as const,
};

export const cronogramasApi = {
  eliminar: (id: number, datos: { motivo: string; lock_version: number }) => api.delete<EliminarCronogramaSalida>(`/cronogramas/${id}`, datos),
  recalcular: (id: number, datos: EdicionEntrada) => api.post<VersionPrevia>(`/cronogramas/${id}/recalcular`, datos),
  alternativas: (id: number, signal?: AbortSignal) => api.get<Alternativas>(`/cronogramas/${id}/alternativas`, undefined, signal),
  guardarVersion: (id: number, datos: GuardarVersionEntrada) => api.post<CronogramaDetalle>(`/cronogramas/${id}/versiones`, datos),
  descartarBorrador: (id: number) => api.delete<CronogramaDetalle>(`/cronogramas/${id}/borrador`),
  publicar: (id: number, lock_version: number) => api.post<CronogramaConAvisos>(`/cronogramas/${id}/publicar`, { lock_version }),
  visto: (id: number, version_id: number) => api.post<CronogramaConAvisos>(`/cronogramas/${id}/visto`, { version_id }),
  vista: (id: number) => api.post<void>(`/cronogramas/${id}/vista`),
  solicitarCorreccion: (id: number, version_id: number, motivo: string) => api.post<CronogramaDetalle>(`/cronogramas/${id}/solicitar-correccion`, { version_id, motivo }),
  mantener: (id: number, comentario: string) => api.post<CronogramaDetalle>(`/cronogramas/${id}/mantener`, { comentario }),
  diferencias: (id: number, base: number, contra: number, signal?: AbortSignal) => api.get<DiferenciasSalida>(`/cronogramas/${id}/diferencias`, { base, contra }, signal),
  eventos: (id: number, signal?: AbortSignal) => api.get<EventoCronograma[]>(`/cronogramas/${id}/eventos`, undefined, signal),
  datosCampo: (id: number, dias = 7, signal?: AbortSignal) => api.get<DatosCampoDia[]>(`/cronogramas/${id}/datos-campo`, { dias }, signal),
  motivos: (signal?: AbortSignal) => api.get<MotivoCorreccion[]>("/motivos-correccion", undefined, signal),
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
