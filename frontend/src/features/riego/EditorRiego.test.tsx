import { describe, expect, it } from "vitest";

import type { RegistroRiego } from "../../services/riego";
import { ciclo } from "../../test/fabricas";
import { esperaParaAplicar } from "./EditorRiego";

const HOY = "2026-11-11";
// 10:00 en Lima (UTC−5).
const AHORA = new Date("2026-11-11T10:00:00-05:00");

function registro(ciclos: RegistroRiego["ciclos"], sin_riego = false): RegistroRiego {
  return {
    id: 1, turno_id: 11, turno_codigo: "TE01", fecha: HOY, version: 1, estado: "provisional",
    origen: "cronograma", sin_riego, motivo: null, comentario: null, carga_id: null,
    creado_at: null, creado_por: null, ciclos,
  };
}

describe("esperaParaAplicar", () => {
  it("los días pasados se marcan aplicado sin esperar", () => {
    expect(esperaParaAplicar(registro([ciclo("22:00", "23:00", 10)]), "2026-11-10", AHORA)).toBeNull();
  });

  it("hoy, solo cuando ya terminó el último ciclo", () => {
    expect(esperaParaAplicar(registro([ciclo("06:00", "07:00", 10)]), HOY, AHORA)).toBeNull();
    expect(esperaParaAplicar(registro([ciclo("06:00", "07:00", 10), ciclo("09:30", "10:30", 8)]), HOY, AHORA))
      .toMatch(/último ciclo \(10:30\)/);
  });

  it("un ciclo que cruza la medianoche espera al día siguiente", () => {
    expect(esperaParaAplicar(registro([ciclo("23:00", "01:00", 10)]), HOY, AHORA)).toMatch(/01:00 del día siguiente/);
  });

  it("un turno sin riego de hoy se puede confirmar ya; un día futuro, nunca", () => {
    expect(esperaParaAplicar(registro([], true), HOY, AHORA)).toBeNull();
    expect(esperaParaAplicar(registro([ciclo("06:00", "07:00", 10)]), "2026-11-12", AHORA)).toMatch(/futuro/);
  });
});
