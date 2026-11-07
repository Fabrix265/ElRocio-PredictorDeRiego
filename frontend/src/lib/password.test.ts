import { describe, expect, it } from "vitest";

import { esquemaNuevoUsuario } from "../features/usuarios/esquemas";
import { erroresPassword, generarPasswordTemporal, passwordValida } from "./password";

describe("política de contraseña (igual que el backend)", () => {
  it("acepta 10 o más caracteres con letras y números", () => {
    expect(passwordValida("riego2026ok")).toBe(true);
    expect(passwordValida("Abcdefghi1")).toBe(true);
    expect(passwordValida("ñandú12345")).toBe(true);
  });

  it("exige al menos 10 caracteres", () => {
    expect(passwordValida("abcdefgh1")).toBe(false);
    expect(erroresPassword("abc1")).toContain("Debe tener al menos 10 caracteres.");
  });

  it("exige letras y números", () => {
    expect(erroresPassword("1234567890")).toContain("Debe incluir al menos una letra.");
    expect(erroresPassword("abcdefghijk")).toContain("Debe incluir al menos un número.");
  });

  it("no puede ser igual al usuario (sin distinguir mayúsculas)", () => {
    expect(passwordValida("jcastillo26", "jcastillo26")).toBe(false);
    expect(passwordValida("JCastillo26", "jcastillo26")).toBe(false);
    expect(erroresPassword("jcastillo26", "  jcastillo26 ")).toContain("No puede ser igual al nombre de usuario.");
    expect(passwordValida("jcastillo26x", "jcastillo26")).toBe(true);
  });

  it("sin usuario solo aplica longitud, letras y números", () => {
    expect(erroresPassword("plan2026riego", null)).toEqual([]);
  });

  it("el generador siempre cumple la política", () => {
    for (let i = 0; i < 200; i++) {
      const clave = generarPasswordTemporal();
      expect(clave).toHaveLength(12);
      expect(erroresPassword(clave, "admin")).toEqual([]);
    }
  });
});

describe("esquema de alta de usuario", () => {
  const base = {
    username: "lparedes",
    nombre: "Luis Paredes",
    correo: "lparedes@example.com",
    rol: "programador" as const,
    password_temporal: "temporal2026",
    confirmar: "temporal2026",
  };

  it("valida un alta correcta", () => {
    expect(esquemaNuevoUsuario.safeParse(base).success).toBe(true);
  });

  it("rechaza contraseña igual al usuario y confirmación distinta", () => {
    const r = esquemaNuevoUsuario.safeParse({ ...base, password_temporal: "lparedes2026", username: "lparedes2026", confirmar: "otra" });
    expect(r.success).toBe(false);
    const caminos = r.success ? [] : r.error.issues.map((i) => i.path.join("."));
    expect(caminos).toContain("password_temporal");
    expect(caminos).toContain("confirmar");
  });

  it("rechaza correo inválido y rol desconocido", () => {
    const r = esquemaNuevoUsuario.safeParse({ ...base, correo: "no-es-correo", rol: "jefe" });
    expect(r.success).toBe(false);
    const caminos = r.success ? [] : r.error.issues.map((i) => i.path.join("."));
    expect(caminos).toEqual(expect.arrayContaining(["correo", "rol"]));
  });
});
