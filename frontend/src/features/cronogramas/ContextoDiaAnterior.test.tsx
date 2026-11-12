import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { reportesApi, type Serie } from "../../services/reportes";
import { seleccionCon } from "../../test/fabricas";
import { ContextoDiaAnterior, RangoContextoDiaAnterior } from "./ContextoDiaAnterior";

vi.mock("../catalogo/SeleccionProvider", () => ({ useSeleccion: () => seleccionCon() }));

const serie = (puntos: Serie["puntos"]): Serie => ({
  fuente: "x", resolucion: "diaria", desde: null, hasta: null, capturado_fecha: null, unidades: {}, puntos,
});

function montar(ui: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("ContextoDiaAnterior", () => {
  it("muestra la ETo y el clima medidos del día anterior a la fecha del cronograma", async () => {
    const serieApi = vi.spyOn(reportesApi, "serie").mockImplementation(async (fuente) =>
      fuente === "clima"
        ? serie([{ fecha: "2026-11-10", eto_mm: 4.2, t_max: 27.5, hr_media: 70, lluvia_mm: 0 }])
        : serie([{ fecha: "2026-11-10", mds_contraccion_um: 150 }]));
    const pronostico = vi.spyOn(reportesApi, "pronostico");
    montar(<ContextoDiaAnterior fecha="2026-11-11" moduloId={1} />);
    expect(await screen.findByText(/^4[.,]2$/)).toBeInTheDocument();
    expect(screen.getByText("Día anterior · mar 10/11")).toBeInTheDocument();
    expect(screen.getByText("150")).toBeInTheDocument();
    expect(screen.queryByText("Pronóstico")).not.toBeInTheDocument();
    expect(serieApi).toHaveBeenCalledWith("clima", "2026-11-10", "2026-11-10", 1, expect.anything());
    expect(pronostico).not.toHaveBeenCalled();
  });

  it("sin clima medido usa el pronóstico de Phytech y lo marca", async () => {
    vi.spyOn(reportesApi, "serie").mockResolvedValue(serie([]));
    vi.spyOn(reportesApi, "pronostico").mockResolvedValue(serie([{ fecha: "2026-11-12", eto_mm: 5.1, t_max: 29, humedad: 65 }]));
    montar(<ContextoDiaAnterior fecha="2026-11-13" moduloId={1} />);
    expect(await screen.findByText("Pronóstico")).toBeInTheDocument();
    expect(screen.getByText(/^5[.,]1$/)).toBeInTheDocument();
  });

  it("sin ningún dato lo dice", async () => {
    vi.spyOn(reportesApi, "serie").mockResolvedValue(serie([]));
    vi.spyOn(reportesApi, "pronostico").mockResolvedValue(serie([]));
    montar(<ContextoDiaAnterior fecha="2026-11-13" moduloId={1} />);
    expect(await screen.findByText("Sin datos del día anterior")).toBeInTheDocument();
  });

  it("en un rango (resultado de Generar) hace una sola consulta por fuente", async () => {
    const serieApi = vi.spyOn(reportesApi, "serie").mockResolvedValue(serie([
      { fecha: "2026-11-10", eto_mm: 4.2 }, { fecha: "2026-11-11", eto_mm: 3.9 },
    ]));
    montar(
      <RangoContextoDiaAnterior fechas={["2026-11-11", "2026-11-12"]} moduloId={1}>
        <ContextoDiaAnterior fecha="2026-11-11" />
        <ContextoDiaAnterior fecha="2026-11-12" />
      </RangoContextoDiaAnterior>,
    );
    expect(await screen.findByText(/^3[.,]9$/)).toBeInTheDocument();
    expect(serieApi).toHaveBeenCalledTimes(2); // clima y planta, una vez cada una
    expect(serieApi).toHaveBeenCalledWith("clima", "2026-11-10", "2026-11-11", 1, expect.anything());
  });
});
