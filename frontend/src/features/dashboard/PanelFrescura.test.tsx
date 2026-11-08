import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { hoyLima, sumarDias } from "../../lib/fechas";
import type { Rol } from "../../lib/roles";
import { datosApi, ingestasApi, type Frescura, type IngestaCorrida } from "../../services/datos";
import { MODULO, seleccionCon, usuarioConRol } from "../../test/fabricas";
import { diasAtraso, progresoIngesta, resumirFrescura } from "./frescura";
import { DIAS_VENTANA_FRESCURA, PanelFrescura } from "./PanelFrescura";

let rol: Rol = "admin";
vi.mock("../auth/AuthProvider", () => ({ useUsuario: () => usuarioConRol(rol) }));
vi.mock("../catalogo/SeleccionProvider", () => ({ useSeleccion: () => seleccionCon() }));

const HOY = hoyLima();
const AYER = sumarDias(HOY, -1);

const FRESCURA: Frescura = {
  fecha: HOY,
  referencia: AYER,
  fuentes: [
    { fuente: "weatherlink", ultima_fecha: sumarDias(AYER, -7), estado: "naranja", huecos: [] },
    { fuente: "riego_aplicado", ultima_fecha: AYER, estado: "verde", huecos: [sumarDias(AYER, -3)] },
    { fuente: "ndvi", ultima_fecha: sumarDias(AYER, -5), estado: "informativo", informativa: true },
    { fuente: "phytech_suelo", ultima_fecha: null, estado: "naranja" },
  ],
};

function corrida(id: number, estado: IngestaCorrida["estado"], extra: Partial<IngestaCorrida> = {}): IngestaCorrida {
  return {
    id,
    fuente: "weatherlink",
    disparo: "manual",
    usuario: "admin",
    inicio_at: new Date().toISOString(),
    estado,
    filas_nuevas: 0,
    filas_actualizadas: 0,
    filas_omitidas: 0,
    conflictos: 0,
    errores: [],
    ...extra,
  };
}

beforeEach(() => {
  rol = "admin";
  vi.spyOn(datosApi, "frescura").mockResolvedValue(FRESCURA);
  vi.spyOn(ingestasApi, "listar").mockResolvedValue([
    corrida(1, "error", { fuente: "phytech_suelo", disparo: "programado", errores: [{ mensaje: "Credenciales rechazadas", status_code: 401 }] }),
  ]);
});

afterEach(() => {
  vi.useRealTimers();
});

function montar() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <PanelFrescura />
    </QueryClientProvider>,
  );
}

describe("PanelFrescura", () => {
  it("muestra cada fuente con su última fecha completa, atraso y huecos", async () => {
    montar();
    const lista = await screen.findByRole("list", { name: "Frescura por fuente" });
    const filas = within(lista).getAllByRole("listitem");
    // Orden fijo: riego aplicado, WeatherLink, Phytech suelo, NDVI.
    expect(filas.map((f) => f.textContent)).toEqual([
      expect.stringContaining("Riego aplicado"),
      expect.stringContaining("WeatherLink"),
      expect.stringContaining("Phytech suelo"),
      expect.stringContaining("NDVI"),
    ]);
    expect(filas[0]).toHaveTextContent("Al día");
    expect(filas[0]).toHaveTextContent("Hueco:");
    expect(filas[1]).toHaveTextContent("Atrasado");
    expect(filas[1]).toHaveTextContent("faltan 7 días");
    expect(filas[2]).toHaveTextContent("Sin datos todavía");
    expect(filas[3]).toHaveTextContent("Informativo");
    expect(screen.getByText("2 fuentes atrasadas · 1 con huecos")).toBeInTheDocument();
    expect(datosApi.frescura).toHaveBeenCalledWith(MODULO.id, HOY, DIAS_VENTANA_FRESCURA, expect.anything());
  });

  it("el programador ve la frescura pero no «Actualizar ahora» ni las corridas", async () => {
    rol = "programador";
    montar();
    await screen.findByRole("list", { name: "Frescura por fuente" });
    expect(screen.queryByRole("button", { name: /Actualizar ahora/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Últimas corridas")).not.toBeInTheDocument();
    expect(ingestasApi.listar).not.toHaveBeenCalled();
  });

  it("el subgerente ve las corridas (sin secretos) pero no puede lanzar la ingesta", async () => {
    rol = "subgerente";
    montar();
    const corridas = await screen.findByRole("list", { name: "Últimas corridas de ingesta" });
    expect(within(corridas).getByText("Phytech suelo")).toBeInTheDocument();
    expect(within(corridas).getByText("Credenciales rechazadas (HTTP 401)")).toBeInTheDocument();
    expect(within(corridas).getByText(/Programada/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Actualizar ahora/ })).not.toBeInTheDocument();
  });

  it("«Actualizar ahora» lanza la ingesta, muestra el avance y al terminar refresca la frescura", async () => {
    rol = "encargado";
    const ejecutar = vi.spyOn(ingestasApi, "ejecutar").mockResolvedValue([corrida(10, "en_curso"), corrida(11, "en_curso", { fuente: "phytech_planta" })]);
    const listar = vi.mocked(ingestasApi.listar);
    montar();
    await screen.findByRole("list", { name: "Últimas corridas de ingesta" });
    listar.mockResolvedValue([corrida(10, "ok"), corrida(11, "en_curso", { fuente: "phytech_planta" })]);
    await userEvent.click(screen.getByRole("button", { name: /Actualizar ahora/ }));
    expect(ejecutar).toHaveBeenCalledWith({});
    expect(await screen.findByRole("progressbar", { name: "Avance de la actualización" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Actualizando/ })).toBeDisabled();
    expect(await screen.findByText("Actualizando: 1 de 2 fuentes terminadas")).toBeInTheDocument();

    const llamadasFrescura = vi.mocked(datosApi.frescura).mock.calls.length;
    listar.mockResolvedValue([corrida(10, "ok"), corrida(11, "ok", { fuente: "phytech_planta" })]);
    // El sondeo consulta GET /ingestas cada 2,5 s hasta que todas terminan.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 2700));
    });
    expect(await screen.findByRole("button", { name: /Actualizar ahora/ })).toBeEnabled();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(vi.mocked(datosApi.frescura).mock.calls.length).toBeGreaterThan(llamadasFrescura);
  }, 10_000);
});

describe("cálculos de frescura e ingestas", () => {
  it("resume atrasadas (sin contar informativas) y huecos", () => {
    expect(resumirFrescura(FRESCURA.fuentes)).toEqual({ atrasadas: 2, conHuecos: 1, alDia: false });
    expect(resumirFrescura([{ fuente: "weatherlink", ultima_fecha: AYER, estado: "verde" }]).alDia).toBe(true);
  });

  it("calcula los días de atraso respecto de ayer", () => {
    expect(diasAtraso({ fuente: "x", ultima_fecha: "2026-11-04", estado: "naranja" }, "2026-11-07")).toBe(3);
    expect(diasAtraso({ fuente: "x", ultima_fecha: "2026-11-07", estado: "verde" }, "2026-11-07")).toBe(0);
    expect(diasAtraso({ fuente: "x", ultima_fecha: null, estado: "naranja" }, "2026-11-07")).toBeNull();
  });

  it("sigue el avance de las corridas lanzadas y da el resultado global", () => {
    expect(progresoIngesta([1, 2], [corrida(1, "ok"), corrida(2, "en_curso")])).toMatchObject({ terminadas: 1, completo: false });
    expect(progresoIngesta([1, 2], [corrida(1, "ok"), corrida(2, "ok")])).toMatchObject({ completo: true, resultado: "ok" });
    expect(progresoIngesta([1, 2], [corrida(1, "ok"), corrida(2, "error")])).toMatchObject({ resultado: "parcial" });
    expect(progresoIngesta([1], [corrida(1, "error")])).toMatchObject({ resultado: "error" });
    // Una corrida que ya no aparece no deja el sondeo colgado si no queda nada en curso.
    expect(progresoIngesta([1, 99], [corrida(1, "ok")])).toMatchObject({ completo: true });
    expect(progresoIngesta([1, 99], [corrida(1, "ok"), corrida(5, "en_curso")])).toMatchObject({ completo: false });
    expect(progresoIngesta([], [])).toMatchObject({ completo: false });
  });
});
