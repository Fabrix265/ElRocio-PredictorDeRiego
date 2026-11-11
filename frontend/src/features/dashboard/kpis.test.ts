import { describe, expect, it } from "vitest";

import { kpisParaRol } from "./kpis";

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
