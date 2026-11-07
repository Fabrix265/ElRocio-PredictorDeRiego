import { describe, expect, it } from "vitest";

import { esquemaNuevoUsuario, MENSAJE_USERNAME } from "../features/usuarios/esquemas";
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

  it("no admite más de 128 caracteres (mismo tope que el backend)", () => {
    expect(erroresPassword("a1".repeat(64))).toEqual([]);
    expect(erroresPassword("a1".repeat(64) + "b")).toContain("No puede tener más de 128 caracteres.");
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

  it("username con el mismo contrato que el backend: 3 a 60, se guarda en minúsculas", () => {
    const largo60 = "a".repeat(60);
    const ok = esquemaNuevoUsuario.safeParse({ ...base, username: `  ${largo60.toUpperCase()} ` });
    expect(ok.success).toBe(true);
    expect(ok.success && ok.data.username).toBe(largo60);
    const mixto = esquemaNuevoUsuario.safeParse({ ...base, username: "L.Paredes_2" });
    expect(mixto.success && mixto.data.username).toBe("l.paredes_2");

    for (const malo of ["ab", "a".repeat(61), "josé", "con espacio"]) {
      const r = esquemaNuevoUsuario.safeParse({ ...base, username: malo });
      expect(r.success, malo).toBe(false);
      expect(r.success ? "" : r.error.issues[0].message).toBe(MENSAJE_USERNAME);
    }
    expect(MENSAJE_USERNAME).toContain("de 3 a 60 caracteres");
  });

  it("rechaza correo inválido y rol desconocido", () => {
    const r = esquemaNuevoUsuario.safeParse({ ...base, correo: "no-es-correo", rol: "jefe" });
    expect(r.success).toBe(false);
    const caminos = r.success ? [] : r.error.issues.map((i) => i.path.join("."));
    expect(caminos).toEqual(expect.arrayContaining(["correo", "rol"]));
  });
});
