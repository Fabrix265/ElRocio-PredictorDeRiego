import { describe, expect, it } from "vitest";
import { cicloPlan, turnoPlan } from "../../test/fabricasCronogramas";
import { ordenarEnFila, solapesEntreTurnos } from "./fila";

describe("Horario en fila", () => {
  it.each([
    [5, 5, 5, 5, 5],
    [5, 6, 5, 5, 5],
    [5, 3, 5, 5, 5],
  ])("encadena por vueltas con los ciclos %j", (...cantidades) => {
    // El orden de riego es el recibido, aunque no coincida con los códigos.
    const turnos = cantidades.map((n, i) => turnoPlan(5 - i, n));
    const original = structuredClone(turnos);
    const nuevos = ordenarEnFila(turnos, 180);
    const porHora = nuevos.flatMap((t) => t.ciclos.map((c) => ({ ...c, turno: t.turno_codigo })))
      .sort((a, b) => a.inicio_min - b.inicio_min);
    const esperado = Array.from({ length: Math.max(...cantidades) }, (_, i) =>
      turnos.filter((t) => t.n_ciclos > i).map((t) => `${t.turno_codigo} ciclo ${i + 1}`),
    ).flat();
    expect(porHora.map((c) => `${c.turno} ciclo ${c.ciclo}`)).toEqual(esperado);
    porHora.forEach((c, i) => expect(c.inicio_min).toBe(i ? porHora[i - 1].fin_min : 180));
    expect(solapesEntreTurnos(nuevos)).toEqual([]);
    expect(turnos).toEqual(original);
    nuevos.forEach((t, i) => t.ciclos.forEach((c, j) => {
      expect(c.riego_m3ha).toBe(original[i].ciclos[j].riego_m3ha);
      expect(c.duracion_min).toBe(original[i].ciclos[j].duracion_min);
    }));
  });

  it("redondea el fin a décimas, conserva la duración y recalcula horas, volumen y día", () => {
    const t = turnoPlan(1);
    t.ciclos = [cicloPlan(1, 180, 10.1), cicloPlan(2, 220, 10.1)];
    t.factor_min_por_m3ha = 9; // Ordenar no debe volver a calcular las duraciones con el factor.
    const [nuevo] = ordenarEnFila([t], 1435.2);
    expect(nuevo.ciclos[0]).toMatchObject({ inicio_min: 1435.2, fin_min: 1445.3,
      hora_inicio: "23:55", hora_fin: "00:05", fin_dia_siguiente: true,
      duracion_min: 10.1, duracion_manual: false, riego_m3ha: 5.05, riego_m3: 50.5 });
    expect(nuevo.ciclos[1].inicio_min).toBe(1445.3);
  });

  it("detecta cada cruce entre turnos una vez y excluye los solapes internos y los contiguos", () => {
    const a = turnoPlan(1), b = turnoPlan(2);
    a.ciclos = [cicloPlan(1, 180, 30), cicloPlan(2, 185, 10)];
    b.ciclos = [cicloPlan(1, 190, 10), cicloPlan(2, 210, 10)];
    expect(solapesEntreTurnos([a, b])).toEqual([
      { a: "TE01 ciclo 1", b: "TE02 ciclo 1" },
      { a: "TE01 ciclo 2", b: "TE02 ciclo 1" },
    ]);
  });
});
