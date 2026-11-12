import { describe, expect, it } from "vitest";

import { kpisParaRol, pieSinRiegoAyer } from "./kpis";

describe("KPIs del dashboard por rol (propuesta §4)", () => {
  it("el programador no ve la comparación con la propuesta del modelo", () => {
    const titulos = kpisParaRol("programador").map((k) => k.titulo);
    expect(titulos).not.toContain("Aplicado vs modelo");
    expect(titulos).toContain("Agua aplicada ayer");
  });

  it.each(["admin", "encargado", "subgerente"] as const)("%s ve los cinco KPIs", (rol) => {
    expect(kpisParaRol(rol).map((k) => k.titulo)).toContain("Aplicado vs modelo");
    expect(kpisParaRol(rol)).toHaveLength(5);
  });
});

describe("pie del KPI de agua sin riego ayer", () => {
  it("dice que faltan datos (no que no se regó) e indica el último registro", () => {
    expect(pieSinRiegoAyer("2026-11-09")).toBe("Sin datos de riego de ayer · último registro: lun 09/11");
  });

  it("sin ningún registro solo dice que faltan datos", () => {
    expect(pieSinRiegoAyer(null)).toBe("Sin datos de riego de ayer");
  });
});
