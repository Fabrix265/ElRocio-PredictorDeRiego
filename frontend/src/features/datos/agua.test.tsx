import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import type { AguaDia, AguaTurno } from "../../services/reportes";
import { csvAgua, diferenciaPct, estadoReal, tooltipAgua, valorAgua, valorApilado } from "./agua";
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

describe("tooltip del gráfico de agua", () => {
  const punto = (seriesIndex: number, seriesName: string, value: number | null) =>
    ({ seriesIndex, seriesName, value, marker: "", axisValueLabel: "mié 11/11" });

  it("muestra la unidad, oculta las series vacías y compara real con publicado", () => {
    const html = tooltipAgua([punto(0, "Real", 45.22), punto(1, "Provisional (aún sin riego real)", null),
      punto(2, "Modelo modificado", 44.67), punto(3, "Modelo", 44.67)], "m3ha", "todos los turnos");
    expect(html).toContain("mié 11/11</strong> · todos los turnos");
    expect(html).toContain("45.22 m³/ha");
    expect(html).not.toContain("Provisional");
    expect(html).toContain("Real vs publicado: +1.2 %");
    // Con las versiones del día, cada línea dice de qué versión del cronograma sale.
    const conVersiones = tooltipAgua([punto(2, "Modelo modificado", 39.85), punto(3, "Modelo", 46.81)],
      "m3ha", "todos los turnos", { 2: 4, 3: 1 });
    expect(conVersiones).toContain("Modelo modificado · v4</span>");
    expect(conVersiones).toContain("Modelo · v1</span><strong>46.81 m³/ha");
  });

  it("con provisional no compara y sin valores avisa", () => {
    const html = tooltipAgua([punto(0, "Real", 300), punto(1, "Provisional", 200), punto(2, "Publicado", 520)], "m3", "TE01");
    expect(html).toContain("200.0 m³");
    expect(html).not.toContain("Real vs publicado");
    expect(html).toContain("Total del día</span><strong>500.0 m³");
    expect(tooltipAgua([punto(0, "Real", null)], "m3", "TE01")).toContain("Sin riego registrado");
  });
});

describe("valores de agua", () => {
  it("separa lo real de lo provisional y promedia m³/ha por superficie", () => {
    expect(valorAgua(dia.turnos, "real", "m3")).toBe(250);
    expect(valorAgua(dia.turnos, "provisional", "m3")).toBe(600);
    expect(valorAgua(dia.turnos, "propuesto", "m3ha")).toBe(10.5); // (220 + 200) / 40 ha
    expect(valorAgua([dia.turnos[0]], "modelo", "m3ha")).toBe(18);
    // Barra apilada en m³/ha: real y provisional sobre los mismos 40 ha (suman la lámina del día).
    expect(valorApilado(dia.turnos, "real", "m3ha")).toBe(6.25); // 250 / 40
    expect(valorApilado(dia.turnos, "provisional", "m3ha")).toBe(15); // 600 / 40
    expect(valorApilado(dia.turnos, "real", "m3")).toBe(250);
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
    expect(within(tabla).getByText("pendiente: 20.0")).toBeInTheDocument();
  });

  it("para el programador no hay columnas del modelo", () => {
    render(<MemoryRouter><TablaAgua dias={[dia]} unidad="m3" conModelo={false} /></MemoryRouter>);
    const encabezados = screen.getAllByRole("columnheader").map((c) => c.textContent);
    expect(encabezados.some((t) => t?.startsWith("Modelo"))).toBe(false);
    expect(encabezados).toContain("Publicado (m³)");
  });
});
