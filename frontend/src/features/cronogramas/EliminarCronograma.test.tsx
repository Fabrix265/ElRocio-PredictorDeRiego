import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Rol } from "../../lib/roles";
import { cronogramasApi, type CronogramaDetalle } from "../../services/cronogramas";
import { prepararRadix, usuarioConRol } from "../../test/fabricas";
import { EliminarCronograma } from "./EliminarCronograma";

let rol: Rol = "encargado";
vi.mock("../auth/AuthProvider", () => ({ useUsuario: () => usuarioConRol(rol) }));

function cronograma(extra: Partial<CronogramaDetalle> = {}): CronogramaDetalle {
  return {
    id: 7, modulo_id: 1, modulo_codigo: "MOD5", fecha: "2026-11-12", estado: "borrador", lock_version: 3,
    num_publicaciones: 0, version_publicada_id: null, borrador_version_id: 21,
    ...extra,
  } as CronogramaDetalle;
}

function montar(c: CronogramaDetalle) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/cronogramas/7"]}>
        <Routes>
          <Route path="/cronogramas/7" element={<EliminarCronograma cronograma={c} bloqueado={false} />} />
          <Route path="/cronogramas" element={<p>Listado de cronogramas</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  prepararRadix();
  rol = "encargado";
  vi.restoreAllMocks();
});

describe("Eliminar cronograma", () => {
  it.each(["programador", "subgerente"] as const)("%s no ve el botón", (r) => {
    rol = r;
    montar(cronograma());
    expect(screen.queryByRole("button", { name: "Eliminar" })).not.toBeInTheDocument();
  });

  it("un borrador nunca publicado se elimina definitivamente con motivo obligatorio", async () => {
    const eliminar = vi.spyOn(cronogramasApi, "eliminar").mockResolvedValue({
      accion: "eliminado", cronograma_id: 7, fecha: "2026-11-12", avisos: [],
    });
    montar(cronograma());
    await userEvent.click(screen.getByRole("button", { name: "Eliminar" }));
    expect(await screen.findByText(/Se eliminará definitivamente/)).toBeInTheDocument();
    const confirmar = screen.getAllByRole("button", { name: "Eliminar" }).at(-1)!;
    expect(confirmar).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox"), "ab");
    expect(confirmar).toBeDisabled();
    await userEvent.type(screen.getByRole("textbox"), "c generado por error");
    await userEvent.click(confirmar);
    expect(eliminar).toHaveBeenCalledWith(7, { motivo: "abc generado por error", lock_version: 3 });
    expect(await screen.findByText("Listado de cronogramas")).toBeInTheDocument();
  });

  it("uno publicado se anula y explica que se conserva para reentrenar", async () => {
    vi.spyOn(cronogramasApi, "eliminar").mockResolvedValue({
      accion: "anulado", cronograma_id: 7, fecha: "2026-11-12", avisos: ["TE05: riego aplicado; se conservó"],
    });
    montar(cronograma({ estado: "visto", num_publicaciones: 1, version_publicada_id: 20 }));
    await userEvent.click(screen.getByRole("button", { name: "Eliminar" }));
    expect(await screen.findByText(/Se anulará/)).toBeInTheDocument();
    expect(screen.getByText(/reentrenar el modelo/)).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox"), "Plan reemplazado");
    await userEvent.click(screen.getByRole("button", { name: "Anular" }));
    expect(await screen.findByText("Listado de cronogramas")).toBeInTheDocument();
  });
});
