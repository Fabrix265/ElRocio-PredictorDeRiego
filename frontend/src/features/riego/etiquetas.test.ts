import { describe, expect, it } from "vitest";

import { normalizarCarga, type GrupoCarga } from "../../services/riego";
import { ciclo } from "../../test/fabricas";
import {
  cambiosParaResultado,
  contarResultados,
  estadoCelda,
  estadoGrupo,
  formatearDuracion,
  resumirCiclos,
  totalAAplicar,
  validarArchivoExcel,
  venceCarga,
} from "./etiquetas";
import { filtrarGrupos } from "./VistaPreviaCarga";

function grupo(id: number, resultado: GrupoCarga["resultado"], aplicar: boolean, fecha = "2026-11-05"): GrupoCarga {
  return { id, fecha, turno_id: 1, turno_codigo: `TE0${(id % 5) + 1}`, resultado, aplicar, ciclos: [], mensajes: [] };
}

describe("resumen de ciclos", () => {
  it("suma m³/ha, m³ y duración y toma el primer inicio y el último fin", () => {
    const r = resumirCiclos([ciclo("08:00", "09:00", 10), ciclo("06:00", "07:30", 15.5), ciclo("23:00", "01:00", 5)]);
    expect(r.n).toBe(3);
    expect(r.m3ha).toBeCloseTo(30.5);
    expect(r.duracionMin).toBe(60 + 90 + 120);
    expect(r.desde).toBe("06:00");
    expect(r.hasta).toBe("01:00");
    expect(r.finDiaSiguiente).toBe(true);
    expect(resumirCiclos(null).n).toBe(0);
  });

  it("formatea la duración en horas y minutos", () => {
    expect(formatearDuracion(45)).toBe("45 min");
    expect(formatearDuracion(120)).toBe("2 h");
    expect(formatearDuracion(85.4)).toBe("1 h 25 min");
  });
});

describe("estado de una celda turno-día", () => {
  it("distingue aplicado, provisional, sin riego y sin registro", () => {
    expect(estadoCelda(undefined)).toBe("sin_registro");
    expect(estadoCelda({ estado: "aplicado", sin_riego: false })).toBe("aplicado");
    expect(estadoCelda({ estado: "provisional", sin_riego: false })).toBe("provisional");
    expect(estadoCelda({ estado: "aplicado", sin_riego: true })).toBe("sin_riego");
  });
});

describe("contadores y casillas de la vista previa", () => {
  const grupos = [
    grupo(1, "nuevo", true),
    grupo(2, "nuevo", false),
    grupo(3, "igual", false),
    grupo(4, "reemplaza_aplicado", false),
    grupo(5, "sin_riego", true),
    grupo(6, "error", false),
    // Un «error» marcado nunca cuenta para aplicar.
    grupo(7, "error", true),
  ];

  it("cuenta por resultado y solo suma a aplicar lo aplicable y marcado", () => {
    const c = contarResultados(grupos);
    expect(c.nuevo).toEqual({ total: 2, aplicar: 1 });
    expect(c.igual).toEqual({ total: 1, aplicar: 0 });
    expect(c.reemplaza_aplicado).toEqual({ total: 1, aplicar: 0 });
    expect(c.sin_riego).toEqual({ total: 1, aplicar: 1 });
    expect(c.error).toEqual({ total: 2, aplicar: 0 });
    expect(totalAAplicar(grupos)).toBe(2);
  });

  it("la casilla de un resultado queda marcada, desmarcada o mixta", () => {
    expect(estadoGrupo(grupos, "nuevo")).toBe("mixto");
    expect(estadoGrupo(grupos, "sin_riego")).toBe(true);
    expect(estadoGrupo(grupos, "reemplaza_aplicado")).toBe(false);
  });

  it("marcar un resultado solo envía los grupos que cambian", () => {
    expect(cambiosParaResultado(grupos, "nuevo", true)).toEqual([{ id: 2, aplicar: true }]);
    expect(cambiosParaResultado(grupos, "nuevo", false)).toEqual([{ id: 1, aplicar: false }]);
    expect(cambiosParaResultado(grupos, "sin_riego", true)).toEqual([]);
  });

  it("el filtro «Con cambios» oculta los iguales y ordena del más reciente al más antiguo", () => {
    const lista = [grupo(1, "nuevo", true, "2026-11-01"), grupo(2, "igual", false, "2026-11-03"), grupo(3, "nuevo", true, "2026-11-04")];
    expect(filtrarGrupos(lista, "cambios").map((g) => g.id)).toEqual([3, 1]);
    expect(filtrarGrupos(lista, "todos").map((g) => g.id)).toEqual([3, 2, 1]);
    expect(filtrarGrupos(lista, "igual").map((g) => g.id)).toEqual([2]);
  });
});

describe("carga de Excel", () => {
  it("vence a las 24 h de subida si el backend no manda vence_at", () => {
    expect(venceCarga({ subido_at: "2026-11-07T10:00:00-05:00" })?.toISOString()).toBe("2026-11-08T15:00:00.000Z");
    expect(venceCarga({ subido_at: "2026-11-07T10:00:00-05:00", vence_at: "2026-11-07T12:00:00-05:00" })?.toISOString()).toBe(
      "2026-11-07T17:00:00.000Z",
    );
  });

  it("valida extensión y tamaño antes de subir (el backend vuelve a validar)", () => {
    const archivo = (nombre: string, bytes: number) => new File([new Uint8Array(bytes)], nombre);
    expect(validarArchivoExcel(archivo("riego.xls", 10))).toMatch(/\.xlsx/);
    expect(validarArchivoExcel(archivo("riego.xlsx", 0))).toMatch(/vacío/);
    expect(validarArchivoExcel(archivo("riego.xlsx", 15 * 1024 * 1024 + 1))).toMatch(/15 MB/);
    expect(validarArchivoExcel(archivo("Riego MOD5.XLSX", 100))).toBeNull();
  });

  it("normaliza la carga del backend: fechas AAAA-MM-DD y ciclos ordenados por inicio", () => {
    const carga = normalizarCarga({
      id: 1,
      modulo_id: 1,
      archivo_nombre: "a.xlsx",
      sha256: "a".repeat(64),
      tamano_bytes: 1,
      subido_at: "2026-11-07T10:00:00-05:00",
      subido_por: "encargado1",
      estado: "previsualizada",
      vence_at: "2026-11-08T10:00:00-05:00",
      confirmado_at: null,
      confirmado_por: null,
      resumen: null,
      grupos: [
        { ...grupo(1, "nuevo", true), fecha: "2026-11-05T00:00:00", ciclos: [ciclo("10:00", "11:00", 5), ciclo("06:00", "07:00", 8)] },
      ],
    });
    expect(carga.grupos).toHaveLength(1);
    expect(carga.grupos[0].fecha).toBe("2026-11-05");
    expect(carga.grupos[0].ciclos.map((c) => c.hora_inicio)).toEqual(["06:00", "10:00"]);
    expect(carga.grupos[0].mensajes).toEqual([]);
  });
});
