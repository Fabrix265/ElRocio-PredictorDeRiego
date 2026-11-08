import { describe, expect, it } from "vitest";

import { extraerTokenFragmento } from "../features/auth/fragmento";
import { analizarDetalle, formatearValor } from "../features/auditoria/etiquetas";
import {
  diasEntre,
  esDiaValido,
  formatearDia,
  formatearDiaCorto,
  formatearFecha,
  formatearFechaCorta,
  formatearFechaHora,
  hoyLima,
  limiteDiaLima,
  listaDias,
  saludoLima,
  sumarDias,
} from "./fechas";

describe("fechas en hora de Lima", () => {
  it("fecha corta de la cabecera en hora de Lima", () => {
    expect(formatearFechaCorta(new Date("2026-11-07T15:00:00Z"))).toBe("sáb 07/11");
    // 23:30 en Lima del sábado = 04:30 UTC del domingo: sigue siendo sábado en Lima.
    expect(formatearFechaCorta(new Date("2026-11-08T04:30:00Z"))).toBe("sáb 07/11");
  });

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

  it("traduce los códigos internos de detalle (motivo) en vez de mostrarlos en crudo", () => {
    expect(formatearValor("password_incorrecta", "motivo")).toBe("Contraseña incorrecta");
    expect(formatearValor("usuario_inexistente", "motivo")).toBe("Usuario inexistente");
    expect(formatearValor("usuario_inactivo", "motivo")).toBe("Usuario inactivo");
    expect(formatearValor("motivo_futuro_x", "motivo")).toBe("Motivo futuro x");
    expect(formatearValor("password_incorrecta", "comentario")).toBe("password_incorrecta");
  });
});

describe("días de calendario", () => {
  it("suma, resta y cuenta días sin depender de la zona del navegador", () => {
    expect(sumarDias("2026-11-01", -1)).toBe("2026-10-31");
    expect(sumarDias("2026-12-31", 1)).toBe("2027-01-01");
    expect(diasEntre("2026-11-01", "2026-11-08")).toBe(7);
    expect(listaDias("2026-11-06", "2026-11-08")).toEqual(["2026-11-06", "2026-11-07", "2026-11-08"]);
    expect(listaDias("2026-11-08", "2026-11-06")).toEqual([]);
  });

  it("formatea un día sin correrlo (2026-11-05 no se vuelve 04/11 en Lima)", () => {
    expect(formatearDia("2026-11-05")).toBe("05/11/2026");
    expect(formatearDiaCorto("2026-11-05")).toBe("jue 05/11");
    expect(formatearDia(null)).toBe("—");
    expect(esDiaValido("2026-02-30")).toBe(false);
    expect(esDiaValido("2026-02-28")).toBe(true);
  });
});
