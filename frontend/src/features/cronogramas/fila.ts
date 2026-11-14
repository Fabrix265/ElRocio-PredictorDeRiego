import type { CicloCronograma, TurnoCronograma } from "../../services/cronogramas";
import { minutosAHora } from "./etiquetas";

const redondear = (n: number, decimales: number) => Number(n.toFixed(decimales));

export function calcular(c: CicloCronograma, t: TurnoCronograma): CicloCronograma {
  const m3ha = redondear(c.riego_m3ha, 2);
  const duracion = redondear(c.duracion_manual || !t.factor_min_por_m3ha ? c.duracion_min : m3ha * t.factor_min_por_m3ha, 1);
  const inicio = redondear(c.inicio_min, 1);
  const fin = redondear(inicio + duracion, 1);
  return { ...c, riego_m3ha: m3ha, riego_m3: redondear(m3ha * t.area_ha, 1), duracion_min: duracion, inicio_min: inicio, fin_min: fin, hora_inicio: minutosAHora(inicio), hora_fin: minutosAHora(fin), fin_dia_siguiente: fin >= 1440 };
}

/** Conserva el orden recibido y encadena el ciclo k de cada turno antes de pasar al k + 1. */
export function ordenarEnFila(turnos: TurnoCronograma[], inicioMin: number): TurnoCronograma[] {
  const nuevos = turnos.map((t) => ({ ...t, ciclos: t.ciclos.map((c) => ({ ...c })) }));
  let inicio = inicioMin;
  const vueltas = Math.max(0, ...turnos.map((t) => t.n_ciclos));
  for (let vuelta = 1; vuelta <= vueltas; vuelta++) {
    for (const t of nuevos) {
      const indice = t.ciclos.findIndex((c) => c.ciclo === vuelta);
      if (indice < 0) continue;
      const c = t.ciclos[indice];
      // Ordenar conserva la duración existente, también cuando procede del modelo.
      const nuevo = calcular({ ...c, inicio_min: inicio, duracion_manual: true }, t);
      t.ciclos[indice] = { ...nuevo, riego_m3ha: c.riego_m3ha, duracion_min: c.duracion_min, duracion_manual: c.duracion_manual };
      inicio = nuevo.fin_min;
    }
  }
  return nuevos;
}

/** Cada pareja aparece una sola vez; los solapes internos los trata el editor. */
export function solapesEntreTurnos(turnos: TurnoCronograma[]): { a: string; b: string }[] {
  const solapes: { a: string; b: string }[] = [];
  for (let i = 0; i < turnos.length; i++) {
    for (let j = i + 1; j < turnos.length; j++) {
      for (const a of turnos[i].ciclos) {
        for (const b of turnos[j].ciclos) {
          if (a.inicio_min < b.fin_min && b.inicio_min < a.fin_min) {
            solapes.push({ a: `${turnos[i].turno_codigo} ciclo ${a.ciclo}`, b: `${turnos[j].turno_codigo} ciclo ${b.ciclo}` });
          }
        }
      }
    }
  }
  return solapes;
}
