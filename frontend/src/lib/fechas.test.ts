import { describe, expect, it } from "vitest";

import { extraerTokenFragmento } from "../features/auth/fragmento";
import { analizarDetalle, formatearValor } from "../features/auditoria/etiquetas";
import { formatearFecha, formatearFechaHora, hoyLima, limiteDiaLima, saludoLima } from "./fechas";

describe("fechas en hora de Lima", () => {
  it("formatea instantes UTC en hora de Lima (UTC-5)", () => {
    expect(formatearFechaHora("2026-11-07T11:15:00Z")).toBe("07/11/2026 06:15");
    expect(formatearFechaHora("2026-11-07T06:15:00-05:00")).toBe("07/11/2026 06:15");
    expect(formatearFecha("2026-11-08T03:00:00Z")).toBe("07/11/2026");
  });

  it("valores vacíos o inválidos se muestran como guion", () => {
    expect(formatearFechaHora(null)).toBe("—");
    expect(formatearFechaHora("no-es-fecha")).toBe("—");
  });

  it("hoyLima a las 23:30 de Lima sigue siendo el mismo día (aunque en UTC ya sea el siguiente)", () => {
    const ahora = new Date("2026-11-08T04:30:00Z"); // 07/11 23:30 en Lima
    expect(hoyLima(ahora)).toBe("2026-11-07");
    expect(saludoLima(ahora)).toBe("Buenas noches");
    expect(saludoLima(new Date("2026-11-07T11:15:00Z"))).toBe("Buenos días");
  });

  it("los límites de un día de Lima van con zona", () => {
    expect(limiteDiaLima("2026-11-07", "inicio")).toBe("2026-11-07T00:00:00-05:00");
    expect(limiteDiaLima("2026-11-07", "fin")).toBe("2026-11-07T23:59:59.999-05:00");
  });
});

describe("token de restablecimiento en el fragmento", () => {
  it("lee #token= y descarta vacíos", () => {
    expect(extraerTokenFragmento("#token=abc.DEF_123")).toBe("abc.DEF_123");
    expect(extraerTokenFragmento("token=xyz")).toBe("xyz");
    expect(extraerTokenFragmento("#otra=1")).toBeNull();
    expect(extraerTokenFragmento("#token=")).toBeNull();
    expect(extraerTokenFragmento("")).toBeNull();
  });
});

describe("detalle de auditoría", () => {
  it("separa antes/después y marca lo que cambió", () => {
    const { cambios, otros } = analizarDetalle({
      antes: { rol: "encargado", activo: true },
      despues: { rol: "subgerente", activo: true },
      motivo: "reorganización",
    });
    expect(cambios).toEqual([
      { campo: "rol", antes: "encargado", despues: "subgerente", cambio: true },
      { campo: "activo", antes: true, despues: true, cambio: false },
    ]);
    expect(otros).toEqual([["motivo", "reorganización"]]);
  });

  it("formatea valores legibles", () => {
    expect(formatearValor(true)).toBe("Sí");
    expect(formatearValor(null)).toBe("—");
    expect(formatearValor("subgerente", "rol")).toBe("Subgerente");
    expect(formatearValor("2026-11-07T11:15:00Z")).toBe("07/11/2026 06:15");
  });
});
