import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { cronogramasApi, type CalculoPulsos } from "../../services/cronogramas";
import { prepararRadix } from "../../test/fabricas";
import { cicloPlan, cronogramaPlan } from "../../test/fabricasCronogramas";
import { EditorPlan } from "./EditorPlan";
import { solapesEntreTurnos } from "./fila";

function montar(pulsos = true) {
  const c = cronogramaPlan();
  if (pulsos) c.version!.calculo_pulsos = { metodo: "pulsos" } as CalculoPulsos;
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={queryClient}><EditorPlan cronograma={c} alCerrar={vi.fn()} alRecargar={vi.fn()} /></QueryClientProvider>);
  return c;
}

const inicio = (turno: number, ciclo = 1) => screen.getByLabelText(`Inicio de TE0${turno}, ciclo ${ciclo}`);

beforeEach(() => {
  vi.restoreAllMocks();
  prepararRadix();
  vi.spyOn(cronogramasApi, "alternativas").mockResolvedValue({
    "1": { "3": [1, 2, 3].map((n) => ({ ...cicloPlan(n, 180 + n * 40, 6), duracion_p10: null, duracion_p90: null })) },
  });
});

describe("Editor del plan por pulsos", () => {
  it("al elegir más ciclos desplaza los demás turnos, elimina solapes y guarda todos los cambios", async () => {
    const c = montar();
    vi.spyOn(cronogramasApi, "motivos").mockResolvedValue([{ id: 1, codigo: "campo", nombre: "Revisión en campo", orden: 1 }]);
    const guardar = vi.spyOn(cronogramasApi, "guardarVersion").mockResolvedValue(c);
    const selector = screen.getAllByRole("combobox", { name: "N.º de ciclos" })[0];
    await waitFor(() => expect(selector).toBeEnabled());
    await userEvent.click(selector);
    await userEvent.click(screen.getByRole("option", { name: "3" }));
    expect(inicio(2)).toHaveValue("03:06");
    expect(inicio(3)).toHaveValue("03:16");
    expect(inicio(1, 2)).toHaveValue("03:26");
    expect(inicio(2, 2)).toHaveValue("03:32");
    expect(inicio(3, 2)).toHaveValue("03:42");
    expect(inicio(1, 3)).toHaveValue("03:52");
    expect(screen.queryByText(/Hay turnos que riegan/)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Guardar corrección" }));
    const dialogo = screen.getByRole("dialog");
    await userEvent.click(await within(dialogo).findByRole("combobox", { name: /Motivo/ }));
    await userEvent.click(screen.getByRole("option", { name: "Revisión en campo" }));
    await userEvent.click(within(dialogo).getByRole("button", { name: "Guardar corrección" }));
    await waitFor(() => expect(guardar).toHaveBeenCalledOnce());
    const enviados = guardar.mock.calls[0][1].turnos;
    expect(enviados.map((t) => t.turno_id)).toEqual([1, 2, 3]);
    const completos = enviados.map((t) => ({ ...c.version!.turnos.find((b) => b.turno_id === t.turno_id)!, ...t,
      ciclos: t.ciclos.map((ciclo) => ({ ...cicloPlan(ciclo.ciclo, ciclo.inicio_min, ciclo.duracion_min!), ...ciclo })) }));
    expect(solapesEntreTurnos(completos)).toEqual([]);
    const ordenados = completos.flatMap((t) => t.ciclos).sort((a, b) => a.inicio_min - b.inicio_min);
    ordenados.slice(1).forEach((ciclo, i) => expect(ciclo.inicio_min).toBe(ordenados[i].fin_min));
  });

  it("reordena por volumen y duración, respeta Inicio manual y permite volver a la fila", () => {
    montar();
    fireEvent.change(screen.getByLabelText("m³/ha de TE01, ciclo 1"), { target: { value: "8" } });
    expect(inicio(2)).toHaveValue("03:16");
    fireEvent.click(screen.getByLabelText("Duración manual de TE01, ciclo 1"));
    fireEvent.change(screen.getByLabelText("Duración de TE01, ciclo 1"), { target: { value: "20" } });
    expect(inicio(2)).toHaveValue("03:20");
    fireEvent.change(inicio(2), { target: { value: "03:05" } });
    expect(inicio(2)).toHaveValue("03:05");
    expect(screen.getByText(/Hay turnos que riegan al mismo tiempo: TE01 ciclo 1 y TE02 ciclo 1/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Ordenar en fila" }));
    expect(inicio(1)).toHaveValue("03:00");
    expect(inicio(2)).toHaveValue("03:20");
    expect(screen.queryByText(/Hay turnos que riegan/)).not.toBeInTheDocument();
  });

  it("sin pulsos conserva los horarios de otros turnos y las acciones anteriores", async () => {
    montar(false);
    fireEvent.change(screen.getByLabelText("m³/ha de TE01, ciclo 1"), { target: { value: "8" } });
    expect(inicio(2)).toHaveValue("03:10");
    const selector = screen.getAllByRole("combobox", { name: "N.º de ciclos" })[0];
    await waitFor(() => expect(selector).toBeEnabled());
    await userEvent.click(selector);
    await userEvent.click(screen.getByRole("option", { name: "3" }));
    expect(inicio(2)).toHaveValue("03:10");
    expect(screen.queryByRole("button", { name: "Ordenar en fila" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Hay turnos que riegan/)).not.toBeInTheDocument();
  });
});
