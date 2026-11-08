import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { hoyLima, sumarDias } from "../../lib/fechas";
import type { Rol } from "../../lib/roles";
import { riegoApi, type RegistroRiego, type VersionRiego } from "../../services/riego";
import { ciclo, MODULO, prepararRadix, seleccionCon, usuarioConRol } from "../../test/fabricas";
import RiegoPage, { validarRango } from "./RiegoPage";

let rol: Rol = "admin";
vi.mock("../auth/AuthProvider", () => ({ useUsuario: () => usuarioConRol(rol) }));
vi.mock("../catalogo/SeleccionProvider", () => ({ useSeleccion: () => seleccionCon() }));

const AYER = sumarDias(hoyLima(), -1);
const ANTEAYER = sumarDias(hoyLima(), -2);

function registro(extra: Partial<RegistroRiego>): RegistroRiego {
  return {
    id: 1,
    turno_id: 11,
    turno_codigo: "TE01",
    fecha: AYER,
    version: 1,
    estado: "aplicado",
    origen: "excel",
    sin_riego: false,
    ciclos: [ciclo("06:00", "07:30", 15.2), ciclo("10:00", "11:00", 10)],
    ...extra,
  };
}

const REGISTROS: RegistroRiego[] = [
  registro({ id: 1, version: 2 }),
  registro({ id: 2, turno_id: 12, turno_codigo: "TE02", estado: "provisional", origen: "cronograma", ciclos: [ciclo("23:00", "00:30", 8)] }),
  registro({ id: 3, fecha: ANTEAYER, sin_riego: true, ciclos: [], motivo: "Clima / lluvia" }),
];

const VERSIONES: VersionRiego[] = [
  { ...registro({ id: 1, version: 2, creado_por: "encargado1" }), vigente: true },
  { ...registro({ id: 9, version: 1, estado: "provisional", origen: "cronograma", ciclos: [ciclo("06:00", "07:00", 12)] }), vigente: false },
];

beforeEach(() => {
  prepararRadix();
  rol = "admin";
  vi.spyOn(riegoApi, "listar").mockResolvedValue(REGISTROS);
  vi.spyOn(riegoApi, "versiones").mockResolvedValue(VERSIONES);
});

function montar() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/riego"]}>
        <RiegoPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RiegoPage", () => {
  it("pide el riego del módulo de la cabecera para los últimos 14 días", async () => {
    montar();
    await screen.findAllByRole("button", { name: /^Ver detalle/ });
    expect(riegoApi.listar).toHaveBeenCalledWith(MODULO.id, sumarDias(hoyLima(), -13), hoyLima(), expect.anything());
  });

  it("muestra cada turno-día con su estado: aplicado, provisional, sin riego y sin registro", async () => {
    montar();
    expect(await screen.findByRole("button", { name: /TE01, .*: Aplicado, 2 ciclos, 25\.2 m³\/ha/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /TE02, .*: Provisional, 1 ciclo/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /TE01, .*: Sin riego/ })).toBeInTheDocument();
    // TE02 de anteayer no tiene registro: se muestra pero no abre detalle.
    expect(screen.getAllByRole("group", { name: /TE02, .*: Sin registro/ }).length).toBeGreaterThan(0);
  });

  it("al tocar un turno-día abre el panel con sus ciclos y el historial de versiones (A, E, S)", async () => {
    rol = "subgerente";
    montar();
    await userEvent.click(await screen.findByRole("button", { name: /TE01, .*: Aplicado/ }));
    const panel = await screen.findByRole("dialog");
    expect(within(panel).getByRole("table", { name: /Ciclos de TE01/ })).toBeInTheDocument();
    expect(within(panel).getByText("06:00–07:30")).toBeInTheDocument();
    expect(await within(panel).findByText("Versión 2")).toBeInTheDocument();
    expect(within(panel).getByText("Original")).toBeInTheDocument();
    expect(within(panel).getByText("Vigente")).toBeInTheDocument();
    expect(riegoApi.versiones).toHaveBeenCalledWith(11, AYER, expect.anything());
  });

  it("el programador ve el detalle en lectura, sin historial de versiones ni carga de Excel", async () => {
    rol = "programador";
    montar();
    await userEvent.click(await screen.findByRole("button", { name: /TE01, .*: Aplicado/ }));
    const panel = await screen.findByRole("dialog");
    expect(within(panel).getByRole("table", { name: /Ciclos de TE01/ })).toBeInTheDocument();
    expect(within(panel).queryByText("Historial de versiones")).not.toBeInTheDocument();
    expect(riegoApi.versiones).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: /Cargar Excel/ })).not.toBeInTheDocument();
  });

  it("solo admin y encargado ven «Cargar Excel»", async () => {
    for (const [r, ve] of [["admin", true], ["encargado", true], ["subgerente", false]] as const) {
      rol = r;
      const { unmount } = montar();
      await screen.findAllByRole("button", { name: /^Ver detalle/ });
      expect(!!screen.queryByRole("link", { name: /Cargar Excel/ })).toBe(ve);
      unmount();
    }
  });

  it("los atajos cambian el rango y un rango inválido no consulta", async () => {
    montar();
    await screen.findAllByRole("button", { name: /^Ver detalle/ });
    await userEvent.click(screen.getByRole("button", { name: "7 días" }));
    expect(riegoApi.listar).toHaveBeenLastCalledWith(MODULO.id, sumarDias(hoyLima(), -6), hoyLima(), expect.anything());
  });

  it("valida el rango de fechas", () => {
    expect(validarRango("2026-11-01", "2026-11-07")).toBeNull();
    expect(validarRango("2026-11-08", "2026-11-07")).toMatch(/posterior/);
    expect(validarRango("2026-01-01", "2026-11-07")).toMatch(/92 días/);
    expect(validarRango("", "2026-11-07")).toMatch(/dos fechas/);
  });
});
