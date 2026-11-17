import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { AguaDia, AguaTurno } from "../../services/reportes";
import { csvAgua, diferenciaPct, estadoReal, valorAgua } from "./agua";
import { TablaAgua } from "./TablaAgua";

const turno = (id: number, extra: Partial<AguaTurno> = {}): AguaTurno => ({
  turno_id: id, turno_codigo: `TE0${id}`, area_ha: 10, aplicado_m3ha: null, aplicado_m3: null, estado_riego: null,
  sin_riego: false, real_m3ha: null, real_m3: null, propuesto_m3ha: 20, propuesto_m3: 200, modelo_m3ha: 18,
  modelo_m3: 180, modificado: false, ...extra,
});

const dia: AguaDia = {
  fecha: "2026-11-09", cronograma_id: 7, propuesta_version: 2, propuesta_origen: "correccion", modelo_version: 1,
  modificado: true, motivo: "Lluvia · =pronóstico", turnos: [
    turno(1, { estado_riego: "aplicado", aplicado_m3: 250, aplicado_m3ha: 25, real_m3: 250, real_m3ha: 25, propuesto_m3ha: 22, propuesto_m3: 220, modificado: true }),
    turno(2, { area_ha: 30, estado_riego: "provisional", aplicado_m3: 600, aplicado_m3ha: 20 }),
  ],
};

describe("valores de agua", () => {
  it("separa lo real de lo provisional y promedia m³/ha por superficie", () => {
    expect(valorAgua(dia.turnos, "real", "m3")).toBe(250);
    expect(valorAgua(dia.turnos, "provisional", "m3")).toBe(600);
    expect(valorAgua(dia.turnos, "propuesto", "m3ha")).toBe(10.5); // (220 + 200) / 40 ha
    expect(valorAgua([dia.turnos[0]], "modelo", "m3ha")).toBe(18);
    expect(estadoReal(dia.turnos)).toBe("parcial");
    expect(diferenciaPct(25, 20)).toBe(25);
    expect(diferenciaPct(null, 20)).toBeNull();
  });

  it("CSV con punto y coma, coma decimal y sin fórmulas en el motivo", () => {
    const filas = csvAgua([dia], "m3ha", true).replace("﻿", "").split("\r\n");
    expect(filas[0].split(";").slice(0, 5)).toEqual(["Fecha", "Turno", "Modelo (m3/ha)", "Modificado / publicado (m3/ha)", "Real (m3/ha)"]);
    expect(filas[1].split(";")).toEqual(["2026-11-09", "TE01", "18", "22", "25", "13,6", "38,9", "Real", "Sí", "Lluvia · =pronóstico"]);
    expect(filas[2].split(";").slice(4, 8)).toEqual(["", "", "", "Provisional"]);
  });
});

describe("TablaAgua", () => {
  it("muestra modelo, modificado y real por día y despliega los turnos", async () => {
    render(<MemoryRouter><TablaAgua dias={[dia]} unidad="m3ha" conModelo /></MemoryRouter>);
    const tabla = screen.getByRole("table", { name: /modelo, modificado y real/ });
    expect(within(tabla).getByText("Real parcial")).toBeInTheDocument();
    expect(within(tabla).getByText("Modificado")).toBeInTheDocument();
    expect(within(tabla).getByRole("link", { name: /v2/ })).toHaveAttribute("href", "/cronogramas/7");
    await userEvent.click(within(tabla).getByRole("button", { name: /lun 09\/11|09\/11/ }));
    expect(within(tabla).getByText("TE02")).toBeInTheDocument();
    expect(within(tabla).getByText("pendiente: 20")).toBeInTheDocument();
  });

  it("para el programador no hay columnas del modelo", () => {
    render(<MemoryRouter><TablaAgua dias={[dia]} unidad="m3" conModelo={false} /></MemoryRouter>);
    const encabezados = screen.getAllByRole("columnheader").map((c) => c.textContent);
    expect(encabezados.some((t) => t?.startsWith("Modelo"))).toBe(false);
    expect(encabezados).toContain("Publicado (m³)");
  });
});
