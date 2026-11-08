import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../../services/httpClient";
import { riegoApi, type CargaRiego, type GrupoCarga } from "../../services/riego";
import { ciclo, MODULO, prepararRadix, seleccionCon } from "../../test/fabricas";
import CargaDetallePage from "./CargaDetallePage";
import CargaNuevaPage from "./CargaNuevaPage";

vi.mock("../catalogo/SeleccionProvider", () => ({ useSeleccion: () => seleccionCon() }));

function grupo(id: number, resultado: GrupoCarga["resultado"], aplicar: boolean, extra: Partial<GrupoCarga> = {}): GrupoCarga {
  return {
    id,
    fecha: `2026-11-0${(id % 6) + 1}`,
    turno_id: 11,
    turno_codigo: "TE01",
    resultado,
    aplicar,
    ciclos: resultado === "sin_riego" ? [] : [ciclo("06:00", "07:00", 12)],
    mensajes: [],
    ...extra,
  };
}

function carga(extra: Partial<CargaRiego> = {}): CargaRiego {
  return {
    id: 5,
    modulo_id: MODULO.id,
    archivo_nombre: "data_riego.xlsx",
    tamano_bytes: 2_400_000,
    subido_at: new Date().toISOString(),
    subido_por: "encargado1",
    estado: "previsualizada",
    vence_at: new Date(Date.now() + 23 * 3600_000).toISOString(),
    grupos: [
      grupo(1, "nuevo", true),
      grupo(2, "nuevo", true),
      grupo(3, "igual", false),
      grupo(4, "reemplaza_provisional", true),
      grupo(5, "reemplaza_aplicado", false, { vigente_origen: "manual", vigente_estado: "aplicado" }),
      grupo(6, "sin_riego", true, { turno_codigo: "TE02" }),
      grupo(7, "error", false, { mensajes: ["La fecha es de hoy o futura."] }),
    ],
    ...extra,
  };
}

beforeEach(() => {
  prepararRadix();
});

function montar(ruta: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[ruta]}>
        <Routes>
          <Route path="/riego" element={<p>Pantalla de riego</p>} />
          <Route path="/riego/cargas/nueva" element={<CargaNuevaPage />} />
          <Route path="/riego/cargas/:id" element={<CargaDetallePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Carga de Excel: subir", () => {
  it("rechaza un archivo que no es .xlsx sin llamar al backend", async () => {
    const subir = vi.spyOn(riegoApi, "subirCarga");
    montar("/riego/cargas/nueva");
    const input = screen.getByLabelText("Archivo Excel de riego");
    await userEvent.upload(input, new File(["x"], "riego.xls"), { applyAccept: false });
    expect(await screen.findByText("El archivo debe ser un Excel .xlsx.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Subir y revisar/ })).toBeDisabled();
    expect(subir).not.toHaveBeenCalled();
  });

  it("sube el archivo con el módulo de la cabecera y abre la vista previa", async () => {
    const subir = vi.spyOn(riegoApi, "subirCarga").mockResolvedValue(carga());
    montar("/riego/cargas/nueva");
    const archivo = new File(["contenido"], "data_riego.xlsx");
    await userEvent.upload(screen.getByLabelText("Archivo Excel de riego"), archivo);
    await userEvent.click(screen.getByRole("button", { name: /Subir y revisar/ }));
    expect(subir).toHaveBeenCalledWith(MODULO.id, archivo);
    expect(await screen.findByRole("heading", { name: "Vista previa de la carga" })).toBeInTheDocument();
  });

  it("muestra el error del backend si el archivo no pasa la validación", async () => {
    vi.spyOn(riegoApi, "subirCarga").mockRejectedValue(new ApiError(422, "El archivo no tiene la hoja MOD5."));
    montar("/riego/cargas/nueva");
    await userEvent.upload(screen.getByLabelText("Archivo Excel de riego"), new File(["x"], "a.xlsx"));
    await userEvent.click(screen.getByRole("button", { name: /Subir y revisar/ }));
    expect(await screen.findByText("El archivo no tiene la hoja MOD5.")).toBeInTheDocument();
  });
});

describe("Carga de Excel: vista previa", () => {
  it("muestra contadores por resultado y cuántos turno-días se aplicarán", async () => {
    vi.spyOn(riegoApi, "carga").mockResolvedValue(carga());
    montar("/riego/cargas/5");
    const resumen = await screen.findByRole("region", { name: "Resumen por resultado" });
    expect(within(resumen).getByRole("button", { name: /Nuevo: 2/ })).toBeInTheDocument();
    expect(within(resumen).getByRole("button", { name: /Igual: 1/ })).toBeInTheDocument();
    expect(within(resumen).getByRole("button", { name: /Reemplaza aplicado: 1/ })).toBeInTheDocument();
    expect(within(resumen).getByRole("button", { name: /Error: 1/ })).toBeInTheDocument();
    // nuevo 2 + reemplaza provisional 1 + sin riego 1 (reemplaza aplicado manual viene desmarcado).
    expect(screen.getByText(/Se aplicarán/)).toHaveTextContent("Se aplicarán 4 turno-días");
    expect(screen.getByLabelText("Aplicar todos: Reemplaza aplicado")).not.toBeChecked();
    expect(screen.getByText("La fecha es de hoy o futura.")).toBeInTheDocument();
  });

  it("desmarcar «sin riego» envía solo esos grupos y actualiza el total al instante", async () => {
    vi.spyOn(riegoApi, "carga").mockResolvedValue(carga());
    let resolver: (c: CargaRiego) => void = () => {};
    const marcar = vi.spyOn(riegoApi, "marcar").mockImplementation(() => new Promise((r) => (resolver = r)));
    montar("/riego/cargas/5");
    await userEvent.click(await screen.findByLabelText("Aplicar todos: Sin riego"));
    expect(marcar).toHaveBeenCalledWith(5, [{ id: 6, aplicar: false }]);
    expect(screen.getByText(/Se aplicarán/)).toHaveTextContent("Se aplicarán 3 turno-días");
    const actualizada = carga();
    actualizada.grupos = actualizada.grupos.map((g) => (g.id === 6 ? { ...g, aplicar: false } : g));
    resolver(actualizada);
    await waitFor(() => expect(screen.getByLabelText("Aplicar todos: Sin riego")).not.toBeChecked());
  });

  it("confirmar aplica la carga y muestra el resultado", async () => {
    vi.spyOn(riegoApi, "carga").mockResolvedValue(carga());
    const confirmar = vi
      .spyOn(riegoApi, "confirmar")
      .mockResolvedValue(carga({ estado: "confirmada", confirmado_at: new Date().toISOString(), confirmado_por: "encargado1" }));
    montar("/riego/cargas/5");
    await userEvent.click(await screen.findByRole("button", { name: "Confirmar" }));
    const dialogo = await screen.findByRole("dialog", { name: "¿Confirmar la carga?" });
    await userEvent.click(within(dialogo).getByRole("button", { name: "Confirmar carga" }));
    expect(confirmar).toHaveBeenCalledWith(5);
    expect(await screen.findByText("Carga confirmada: 4 turno-días aplicados")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Ver riego aplicado/ })).toHaveAttribute("href", "/riego");
  });

  it("si al confirmar la carga venció (409), lo explica y ofrece subirla otra vez", async () => {
    vi.spyOn(riegoApi, "carga").mockResolvedValue(carga());
    vi.spyOn(riegoApi, "confirmar").mockRejectedValue(
      new ApiError(409, "La carga venció porque cambió un registro comparado. Súbela otra vez."),
    );
    montar("/riego/cargas/5");
    await userEvent.click(await screen.findByRole("button", { name: "Confirmar" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Confirmar carga" }));
    expect(await screen.findByText("La carga venció")).toBeInTheDocument();
    expect(screen.getByText(/cambió un registro comparado/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Subir otra vez/ })).toHaveAttribute("href", "/riego/cargas/nueva");
    expect(screen.getByRole("button", { name: "Confirmar" })).toBeDisabled();
  });

  it("una carga vencida (estado o 24 h cumplidas) no se puede confirmar ni marcar", async () => {
    vi.spyOn(riegoApi, "carga").mockResolvedValue(carga({ vence_at: new Date(Date.now() - 60_000).toISOString() }));
    montar("/riego/cargas/5");
    expect(await screen.findByText("La carga venció")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirmar" })).toBeDisabled();
    expect(screen.getByLabelText("Aplicar todos: Nuevo")).toBeDisabled();
  });

  it("descartar pide confirmación y vuelve a Riego aplicado", async () => {
    vi.spyOn(riegoApi, "carga").mockResolvedValue(carga());
    const descartar = vi.spyOn(riegoApi, "descartar").mockResolvedValue(carga({ estado: "descartada" }));
    montar("/riego/cargas/5");
    await userEvent.click(await screen.findByRole("button", { name: "Descartar" }));
    const dialogo = await screen.findByRole("dialog", { name: "¿Descartar la carga?" });
    await userEvent.click(within(dialogo).getByRole("button", { name: "Descartar" }));
    expect(descartar).toHaveBeenCalledWith(5);
    expect(await screen.findByText("Pantalla de riego")).toBeInTheDocument();
  });
});
