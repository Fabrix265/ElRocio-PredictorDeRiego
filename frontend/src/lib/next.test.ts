import { describe, expect, it } from "vitest";

import { sanearNext, urlLoginCon } from "./next";

describe("sanearNext", () => {
  it("acepta rutas relativas de la app con query y fragmento", () => {
    expect(sanearNext("/usuarios")).toBe("/usuarios");
    expect(sanearNext("/cronogramas/15?tab=plan#ciclos")).toBe("/cronogramas/15?tab=plan#ciclos");
  });

  it("vuelve al inicio si no hay valor", () => {
    expect(sanearNext(null)).toBe("/");
    expect(sanearNext(undefined)).toBe("/");
    expect(sanearNext("")).toBe("/");
    expect(sanearNext("   ")).toBe("/");
  });

  it.each([
    "https://evil.example/robar",
    "http://localhost:5173/usuarios",
    "//evil.example",
    "///evil.example",
    "/\\evil.example",
    "\\\\evil.example",
    "javascript:alert(1)",
    "usuarios",
    "/ruta\u0000nula",
    "/ruta\nsalto",
    "/foo\\bar",
  ])("rechaza %j", (valor) => {
    expect(sanearNext(valor)).toBe("/");
  });

  it("evita volver a las pantallas de acceso", () => {
    expect(sanearNext("/login")).toBe("/");
    expect(sanearNext("/login?next=/usuarios")).toBe("/");
    expect(sanearNext("/recuperar")).toBe("/");
    expect(sanearNext("/restablecer#token=abc")).toBe("/");
  });

  it("respeta el valor por defecto indicado", () => {
    expect(sanearNext("//x", "/inicio")).toBe("/inicio");
  });
});

describe("urlLoginCon", () => {
  it("guarda la ruta actual codificada en next", () => {
    expect(urlLoginCon("/auditoria?accion=login")).toBe("/login?next=%2Fauditoria%3Faccion%3Dlogin");
  });

  it("omite next para el inicio o rutas no válidas", () => {
    expect(urlLoginCon("/")).toBe("/login");
    expect(urlLoginCon("//evil.example")).toBe("/login");
  });
});
