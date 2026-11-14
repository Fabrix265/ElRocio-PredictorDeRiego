import type { CicloCronograma, CronogramaDetalle, TurnoCronograma } from "../services/cronogramas";
import { minutosAHora } from "../features/cronogramas/etiquetas";

export function cicloPlan(ciclo: number, inicio = 180, duracion = 10): CicloCronograma {
  return {
    ciclo, inicio_min: inicio, fin_min: inicio + duracion, duracion_min: duracion,
    riego_m3ha: duracion / 2, riego_m3: duracion * 5, duracion_manual: false,
    hora_inicio: minutosAHora(inicio), hora_fin: minutosAHora(inicio + duracion),
    fin_dia_siguiente: inicio + duracion >= 1440, ciclo_modelo: ciclo, campos_editados: [],
    m3ha_p10: null, m3ha_p90: null, inicio_desde_min: null, inicio_hasta_min: null,
  };
}

export function turnoPlan(id: number, n = 2): TurnoCronograma {
  return {
    turno_id: id, turno_codigo: `TE${String(id).padStart(2, "0")}`, n_ciclos: n, n_ciclos_modelo: n,
    area_ha: 10, factor_min_por_m3ha: 2, caudal_m3h: 300,
    total_m3ha: 5 * n, total_m3: 50 * n, total_min: 10 * n,
    ciclos: Array.from({ length: n }, (_, i) => cicloPlan(i + 1, 180 + i * 30 + (id - 1) * 10)),
  };
}

export function cronogramaPlan(turnos = [turnoPlan(1), turnoPlan(2), turnoPlan(3)]): CronogramaDetalle {
  return {
    id: 7, modulo_id: 1, modulo_codigo: "MOD5", fecha: "2026-11-14", estado: "borrador",
    lock_version: 3, num_publicaciones: 0, version_publicada_id: null, borrador_version_id: 21,
    tiene_borrador_cambios: false, actualizado_at: "2026-11-14T08:00:00-05:00",
    visto_version_id: null, visto_programador_at: null, visto_por: null,
    correccion_solicitada_at: null, correccion_solicitada_por: null, correccion_solicitada_motivo: null,
    mi_ultimo_visto_numero: null, versiones: [],
    version: {
      id: 21, numero: 1, origen: "modelo", creado_at: "2026-11-14T08:00:00-05:00", creado_por: null,
      preliminar: false, datos_incompletos: false, regenerado: false, desactualizado: false,
      publicada_at: null, publicada_por: null, es_borrador: true, es_publicada: false,
      modelo_version: null, generacion_id: null, motivo_codigo: null, motivo_comentario: null,
      total_m3: turnos.reduce((s, t) => s + t.total_m3, 0), turnos, calculo_pulsos: null,
    },
  };
}
