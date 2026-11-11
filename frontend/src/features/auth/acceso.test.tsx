import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Rol } from "../../lib/roles";
import { ACCESO } from "../../lib/roles";
import type { Usuario } from "../../services/tipos";
import { itemsParaRol } from "../layout/navegacion";
import { decidirAcceso, type EstadoSesion } from "./acceso";
import { RutaProtegida } from "./RutaProtegida";

function usuario(rol: Rol, extra: Partial<Usuario> = {}): Usuario {
  return {
    id: 1,
    username: "usuario",
    nombre: "Usuario Prueba",
    correo: "u@example.com",
    rol,
    activo: true,
    debe_cambiar_password: false,
    ultimo_acceso_at: null,
    ...extra,
  };
}

describe("decidirAcceso", () => {
  it("espera mientras se verifica la sesión", () => {
    expect(decidirAcceso({ estado: "cargando", usuario: null, ruta: "/" })).toEqual({ tipo: "cargando" });
  });

  it("si no se pudo verificar la sesión (red o 5xx), no manda al login", () => {
    expect(decidirAcceso({ estado: "sin_conexion", usuario: null, ruta: "/usuarios" })).toEqual({ tipo: "sin_conexion" });
  });

  it("sin sesión manda al login guardando la ruta en next", () => {
    expect(decidirAcceso({ estado: "anonimo", usuario: null, ruta: "/usuarios?rol=admin" })).toEqual({
      tipo: "redirigir",
      a: "/login?next=%2Fusuarios%3Frol%3Dadmin",
    });
    expect(decidirAcceso({ estado: "anonimo", usuario: null, ruta: "/" })).toEqual({ tipo: "redirigir", a: "/login" });
  });

  it("tras cerrar sesión a propósito va al login sin next", () => {
    expect(decidirAcceso({ estado: "anonimo", usuario: null, ruta: "/usuarios", salidaVoluntaria: true })).toEqual({
      tipo: "redirigir",
      a: "/login",
    });
  });

  it("con contraseña temporal fuerza el cambio, salvo en esa misma pantalla", () => {
    const u = usuario("admin", { debe_cambiar_password: true });
    expect(decidirAcceso({ estado: "autenticado", usuario: u, ruta: "/usuarios" })).toEqual({
      tipo: "redirigir",
      a: "/cambiar-password",
    });
    expect(decidirAcceso({ estado: "autenticado", usuario: u, ruta: "/cambiar-password?next=%2F" })).toEqual({
      tipo: "permitido",
    });
  });

  const casos: Array<[keyof typeof ACCESO, Rol, boolean]> = [
    ["usuarios", "admin", true],
    ["usuarios", "encargado", false],
    ["usuarios", "subgerente", false],
    ["usuarios", "programador", false],
    ["auditoria", "admin", true],
    ["auditoria", "subgerente", true],
    ["auditoria", "encargado", false],
    ["auditoria", "programador", false],
    ["generar", "admin", true],
    ["generar", "encargado", true],
    ["generar", "subgerente", false],
    ["generar", "programador", false],
    ["cronogramas", "programador", true],
    ["riego", "subgerente", true],
    ["riego", "programador", true],
    ["cargaRiego", "admin", true],
    ["cargaRiego", "encargado", true],
    ["cargaRiego", "subgerente", false],
    ["cargaRiego", "programador", false],
    ["datos", "programador", true],
  ];

  it.each(casos)("pantalla %s con rol %s → permitido=%s", (pantalla, rol, permitido) => {
    const d = decidirAcceso({ estado: "autenticado", usuario: usuario(rol), roles: ACCESO[pantalla], ruta: `/${pantalla}` });
    expect(d.tipo).toBe(permitido ? "permitido" : "prohibido");
  });

  it("el menú muestra a cada rol solo sus pantallas", () => {
    const rutas = (rol: Rol) => itemsParaRol(rol).map((i) => i.ruta);
    expect(rutas("admin")).toEqual(["/", "/generar", "/cronogramas", "/riego", "/datos", "/auditoria", "/usuarios"]);
    expect(rutas("encargado")).toEqual(["/", "/generar", "/cronogramas", "/riego", "/datos"]);
    expect(rutas("subgerente")).toEqual(["/", "/cronogramas", "/riego", "/datos", "/auditoria"]);
    expect(rutas("programador")).toEqual(["/", "/cronogramas", "/riego", "/datos"]);
  });
});

// --- RutaProtegida con un AuthProvider simulado (vi.mock se eleva sobre los imports) ---

const estadoAuth = vi.hoisted(() => ({
  estado: "anonimo" as EstadoSesion,
  usuario: null as Usuario | null,
  salidaVoluntaria: false,
}));

vi.mock("./AuthProvider", () => ({
  useAuth: () => estadoAuth,
}));

function Ubicacion() {
  const l = useLocation();
  return <p data-testid="ubicacion">{l.pathname + l.search}</p>;
}

function montar(rutaInicial: string) {
  return render(
    <MemoryRouter initialEntries={[rutaInicial]}>
      <Routes>
        <Route path="/login" element={<Ubicacion />} />
        <Route path="/cambiar-password" element={<Ubicacion />} />
        <Route
          path="/usuarios"
          element={
            <RutaProtegida roles={ACCESO.usuarios}>
              <p>Pantalla de usuarios</p>
            </RutaProtegida>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("RutaProtegida", () => {
  beforeEach(() => {
    estadoAuth.estado = "anonimo";
    estadoAuth.usuario = null;
  });

  it("redirige al login con next si no hay sesión", () => {
    montar("/usuarios?q=ana");
    expect(screen.getByTestId("ubicacion")).toHaveTextContent("/login?next=%2Fusuarios%3Fq%3Dana");
  });

  it("muestra la página 403 a un rol sin permiso", () => {
    estadoAuth.estado = "autenticado";
    estadoAuth.usuario = usuario("encargado");
    montar("/usuarios");
    expect(screen.getByText("No tienes acceso a esta sección")).toBeInTheDocument();
    expect(screen.queryByText("Pantalla de usuarios")).not.toBeInTheDocument();
  });

  it("deja pasar al rol permitido", () => {
    estadoAuth.estado = "autenticado";
    estadoAuth.usuario = usuario("admin");
    montar("/usuarios");
    expect(screen.getByText("Pantalla de usuarios")).toBeInTheDocument();
  });

  it("fuerza el cambio de contraseña temporal", () => {
    estadoAuth.estado = "autenticado";
    estadoAuth.usuario = usuario("admin", { debe_cambiar_password: true });
    montar("/usuarios");
    expect(screen.getByTestId("ubicacion")).toHaveTextContent("/cambiar-password");
  });
});
