import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Rol } from "../../lib/roles";
import { copilotoApi, type Resumen, type Sugerencia } from "../../services/copiloto";
import { prepararRadix, seleccionCon, usuarioConRol } from "../../test/fabricas";
import { CopilotoPage } from "./CopilotoPage";
import { nombreAgente, ordenarPorSeveridad } from "./etiquetas";

let rol: Rol = "encargado";
vi.mock("../auth/AuthProvider", () => ({ useUsuario: () => usuarioConRol(rol) }));
vi.mock("../catalogo/SeleccionProvider", () => ({ useSeleccion: () => seleccionCon() }));

const RESUMEN: Resumen = {
  modulo: { id: 1, codigo: "EN01-MOD5", nombre: "Módulo 5", area_ha: 25, turnos: ["TE01", "TE02"] },
  fecha: "2026-11-08",
  generado_at: "2026-11-08T06:00:00-05:00",
  plan_hoy: {
    fecha: "2026-11-08", cronograma_id: 7, estado: "publicado", estado_texto: "publicado", publicado: true, version: 2,
    eto_dia_anterior_mm: 4.8, eto_dia_anterior_es_pronostico: false, eto_pronostico_mm: 3.4,
    total_m3: 1130, total_m3ha: 45.2, turnos: [],
  },
  plan_manana: null,
  alertas: [
    { codigo: "demanda_alta", severidad: "info", titulo: "Se viene más demanda de agua", detalle: "ETo 4,6 mm", fecha: "2026-11-09", turno_codigo: null, valores: {} },
    { codigo: "riego_sin_respuesta", severidad: "alta", titulo: "Se regó, pero el suelo casi no respondió", detalle: "Revisar goteros", fecha: "2026-11-07", turno_codigo: null, valores: {} },
  ],
  conteo_alertas: { alta: 1, media: 0, info: 1 },
  sugerencias_pendientes: 1,
};

const SUGERENCIA: Sugerencia = {
  id: 3, modulo_id: 1, modulo_codigo: "EN01-MOD5", fecha: "2026-11-07", turno_codigo: "TE03", tipo: "revisar_equipo",
  alerta_codigo: "riego_sin_respuesta", titulo: "Revisar la válvula del TE03", detalle: "El suelo no respondió.",
  estado: "pendiente", propuesta_por: "agente:n8n-copiloto", created_at: "2026-11-08T06:01:00-05:00",
  resuelto_por: null, resuelto_at: null, comentario_resolucion: null,
};

function montar() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter><CopilotoPage /></MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  prepararRadix();
  rol = "encargado";
  vi.restoreAllMocks();
  vi.spyOn(copilotoApi, "resumen").mockResolvedValue(RESUMEN);
  vi.spyOn(copilotoApi, "sugerencias").mockResolvedValue([SUGERENCIA]);
});

describe("Copiloto", () => {
  it("muestra el plan con m³, m³/ha y ETo, y las alertas de mayor a menor severidad", async () => {
    montar();
    const alertas = await screen.findByRole("list", { name: "Alertas" });
    const titulos = within(alertas).getAllByText(/Se regó|Se viene/).map((n) => n.textContent);
    expect(titulos).toEqual(["Se regó, pero el suelo casi no respondió", "Se viene más demanda de agua"]);
    expect(screen.getByText(/^ETo día anterior 4[.,]8 mm$/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /1130|1 130|m³\/ha/ })).toHaveAttribute("href", "/cronogramas/7");
    expect(await screen.findByText("Revisar la válvula del TE03")).toBeInTheDocument();
    expect(screen.getByText(/Agente n8n-copiloto/)).toBeInTheDocument();
  });

  it("el encargado descarta con motivo obligatorio", async () => {
    const descartar = vi.spyOn(copilotoApi, "descartar").mockResolvedValue({ ...SUGERENCIA, estado: "descartada" });
    montar();
    await userEvent.click(await screen.findByRole("button", { name: "Descartar" }));
    const dialogo = await screen.findByRole("dialog");
    const confirmar = within(dialogo).getByRole("button", { name: "Descartar" });
    expect(confirmar).toBeDisabled();
    await userEvent.type(within(dialogo).getByRole("textbox"), "Ya se revisó ayer");
    await userEvent.click(confirmar);
    expect(descartar).toHaveBeenCalledWith(3, "Ya se revisó ayer");
  });

  it("el subgerente ve las sugerencias pero no las resuelve", async () => {
    rol = "subgerente";
    montar();
    expect(await screen.findByText("Revisar la válvula del TE03")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Aprobar" })).not.toBeInTheDocument();
  });
});

describe("etiquetas del copiloto", () => {
  it("ordena por severidad y nombra al agente", () => {
    expect(ordenarPorSeveridad([{ severidad: "info" }, { severidad: "alta" }, { severidad: "media" }] as const).map((a) => a.severidad))
      .toEqual(["alta", "media", "info"]);
    expect(nombreAgente("agente:n8n")).toBe("Agente n8n");
    expect(nombreAgente("otro")).toBe("otro");
  });
});
