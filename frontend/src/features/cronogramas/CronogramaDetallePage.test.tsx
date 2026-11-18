import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { cronogramasApi } from "../../services/cronogramas";
import { reportesApi } from "../../services/reportes";
import { prepararRadix, usuarioConRol } from "../../test/fabricas";
import { cicloPlan, cronogramaPlan, turnoPlan } from "../../test/fabricasCronogramas";
import CronogramaDetallePage, { TablaPorHora } from "./CronogramaDetallePage";

vi.mock("../auth/AuthProvider", () => ({ useUsuario: () => usuarioConRol("encargado") }));
vi.mock("./ContextoDiaAnterior", () => ({ ContextoDiaAnterior: () => null }));
vi.mock("./Gantt", () => ({ Gantt: () => <p>Gráfico de horarios</p> }));

beforeEach(() => {
  vi.restoreAllMocks();
  prepararRadix();
});

describe("Versiones", () => {
  it("muestra los m³ y m³/ha de cada versión", async () => {
    const c = cronogramaPlan();
    const { turnos: _t, desactualizado: _d, calculo_pulsos: _p, ...resumen } = c.version!;
    c.versiones = [{ ...resumen, numero: 2, id: 22, total_m3: 3227.7, total_m3ha: 51.37 }, { ...resumen, total_m3: 3100, total_m3ha: 49.34 }];
    c.borrador_version_id = 22; // el comparador abre v1 (la más antigua) contra el borrador v2
    vi.spyOn(cronogramasApi, "detalle").mockResolvedValue(c);
    const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={cliente}><MemoryRouter initialEntries={["/cronogramas/7"]}>
      <Routes><Route path="/cronogramas/:id" element={<CronogramaDetallePage />} /></Routes>
    </MemoryRouter></QueryClientProvider>);
    await userEvent.click(await screen.findByRole("tab", { name: "Versiones" }));
    const lista = screen.getByRole("list", { name: "Versiones" });
    expect(within(lista).getByText("3,227.7 m³ · 51.37 m³/ha")).toBeInTheDocument();
    expect(within(lista).getByText("3,100.0 m³ · 49.34 m³/ha")).toBeInTheDocument();
    // Comparador: total del día de cada versión y la diferencia.
    const total = screen.getByRole("table", { name: "Total del día en v1 y v2" });
    const filas = within(total).getAllByRole("row").slice(1).map((f) => [...f.children].map((c) => c.textContent));
    expect(filas).toEqual([
      ["Agua total (m³)", "3,100.0", "3,227.7", "+127.7 (+4.1 %)"],
      ["Lámina (m³/ha)", "49.34", "51.37", "+2.03 (+4.1 %)"],
    ]);
  });
});

describe("Lectura por horario", () => {
  it("ordena por minutos absolutos, desempata por turno y muestra el día siguiente", () => {
    const a = turnoPlan(2), b = turnoPlan(1);
    a.ciclos = [cicloPlan(1, 360), cicloPlan(2, 1450)];
    b.ciclos = [cicloPlan(1, 180), cicloPlan(2, 360)];
    render(<TablaPorHora turnos={[a, b]} />);
    const tabla = screen.getByRole("table", { name: "Plan por horario" });
    expect(within(tabla).getAllByRole("columnheader").map((c) => c.textContent)).toEqual(
      ["Turno", "Ciclo", "Hora inicio", "Hora fin", "Duración (min)", "m³/ha", "m³"]);
    const filas = within(tabla).getAllByRole("row").slice(1);
    const total = filas.pop()!;
    expect(filas.map((fila) => within(fila).getAllByRole("cell").slice(0, 4).map((c) => c.textContent))).toEqual([
      ["TE01", "1", "03:00", "03:10"], ["TE02", "1", "06:00", "06:10"],
      ["TE01", "2", "06:00", "06:10"], ["TE02", "2", "00:10 (+1 día)", "00:20 (+1 día)"],
    ]);
    // Total: minutos, m³/ha del plan (m³ ÷ ha de los turnos) y m³.
    expect(within(total).getAllByRole("cell").map((c) => c.textContent)).toEqual(["Total", "40.0", "10.00", "200.0"]);
  });

  it("empieza por horario, conserva la opción al navegar y la envía al exportar PDF y Excel", async () => {
    const c = cronogramaPlan();
    vi.spyOn(cronogramasApi, "detalle").mockResolvedValue(c);
    const exportar = vi.spyOn(reportesApi, "exportarCronograma").mockResolvedValue("plan.xlsx");
    const cliente = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={cliente}><MemoryRouter initialEntries={["/cronogramas/7"]}>
      <Routes><Route path="/cronogramas/:id" element={<CronogramaDetallePage />} /></Routes>
    </MemoryRouter></QueryClientProvider>);
    expect(await screen.findByRole("table", { name: "Plan por horario" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "PDF" }));
    await waitFor(() => expect(exportar).toHaveBeenCalledWith(7, "pdf", "hora"));
    await userEvent.click(screen.getByRole("combobox", { name: "Orden del plan" }));
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Por horario", "Por turno"]);
    await userEvent.click(screen.getByRole("option", { name: "Por turno" }));
    expect(screen.getByRole("table", { name: "Plan por turno" })).toBeInTheDocument();
    expect(screen.getAllByText(/m³\/ha por día/).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("tab", { name: "Gantt" }));
    await userEvent.click(screen.getByRole("tab", { name: "Plan" }));
    expect(screen.getByRole("table", { name: "Plan por turno" })).toBeInTheDocument();
    for (const [boton, formato] of [["PDF", "pdf"], ["Excel", "xlsx"]]) {
      await waitFor(() => expect(screen.getByRole("button", { name: boton })).toBeEnabled());
      await userEvent.click(screen.getByRole("button", { name: boton }));
      await waitFor(() => expect(exportar).toHaveBeenCalledWith(7, formato, "turno"));
    }
    await userEvent.click(screen.getByRole("button", { name: "Corregir" }));
    expect(screen.queryByRole("combobox", { name: "Orden del plan" })).not.toBeInTheDocument();
  });
});
