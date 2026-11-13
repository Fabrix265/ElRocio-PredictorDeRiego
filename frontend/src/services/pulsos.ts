/**
 * Parámetros del riego por pulsos por módulo (los datos fijos de la planilla de riego por pulsos).
 *
 * - GET /modulos/{id}/parametros-pulsos → 200 ParametrosPulsos (todos los roles)
 * - PUT /modulos/{id}/parametros-pulsos → 200 ParametrosPulsos (admin y encargado; auditado)
 *        422 con el detalle de lo que no cuadra (p. ej. una curva que no suma 100 %)
 * Fracciones en 0–1 (0,14 = 14 %). Curvas: "1"/"2"/"3" → hora ("3".."20") → %.
 */
import { api } from "./httpClient";

export type ModoVentana = "automatico_con_respaldo" | "automatico" | "curva_1" | "curva_2" | "curva_3";

export interface ParametrosPulsosEntrada {
  activo: boolean;
  textura_suelo: string;
  capacidad_campo: number;
  punto_marchitez: number;
  agotamiento_maximo: number;
  infiltracion_basica_mmh: number;
  ancho_humedo_m: number;
  profundidad_raices_m: number;
  diametro_bulbo_m: number | null;
  distancia_hileras_m: number;
  distancia_plantas_m: number;
  mangueras_por_hilera: number;
  separacion_mangueras_m: number;
  distancia_goteros_m: number;
  caudal_gotero_lh: number;
  reposo_min_por_hora: number;
  eficiencia_aplicacion: number;
  fase_fenologica: string;
  agotamiento_por_fase: Record<string, number>;
  agotamiento_automatico: boolean;
  umbral_etr_1: number;
  umbral_etr_2: number;
  modo_ventana: ModoVentana;
  curvas: Record<string, Record<string, number>>;
  ajustar_pulso_al_total: boolean;
}

export interface DerivadosPulsos {
  turnos: number;
  diametro_bulbo_m: number;
  ancho_bulbos_m: number;
  franja_continua: boolean;
  ancho_efectivo_m: number;
  volumen_explorado_m3ha: number;
  agua_util: number;
  agua_disponible_m3ha: number;
  capacidad_riego_m3hah: number;
  intensidad_mmh: number;
  plantas_ha: number;
  goteros_ha: number;
  agotamiento_fase: number;
  agotamiento_max_bloque: number;
  agotamiento_operativo: number;
  amortiguacion_m3ha: number;
  volumen_pulso_m3ha: number;
  minutos_pulso: number;
}

export interface ParametrosPulsos extends ParametrosPulsosEntrada {
  modulo_id: number;
  guardado: boolean;
  actualizado_at: string | null;
  actualizado_por: string | null;
  derivados: DerivadosPulsos | null;
  avisos: string[];
}

export const clavePulsos = {
  parametros: (moduloId: number) => ["parametros-pulsos", moduloId] as const,
};

export const pulsosApi = {
  obtener: (moduloId: number, signal?: AbortSignal) =>
    api.get<ParametrosPulsos>(`/modulos/${moduloId}/parametros-pulsos`, undefined, signal),
  guardar: (moduloId: number, datos: ParametrosPulsosEntrada) =>
    api.put<ParametrosPulsos>(`/modulos/${moduloId}/parametros-pulsos`, datos),
};
