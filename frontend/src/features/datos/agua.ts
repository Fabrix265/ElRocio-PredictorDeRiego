import type { AguaDia, AguaTurno } from "../../services/reportes";

/** Unidad del gráfico y la tabla de agua. */
export type UnidadAgua = "m3ha" | "m3";

/** Qué riego se mide: lo real, lo provisional pendiente, lo publicado (modelo modificado) y el modelo. */
export type SerieAgua = "real" | "provisional" | "propuesto" | "modelo";

/** m³ de una serie en un turno-día (null si no hay dato). */
export function m3De(t: AguaTurno, serie: SerieAgua): number | null {
  if (serie === "real") return t.real_m3 ?? (t.estado_riego === "aplicado" ? t.aplicado_m3 : null);
  if (serie === "provisional") return t.estado_riego === "provisional" ? t.aplicado_m3 : null;
  return serie === "propuesto" ? t.propuesto_m3 : t.modelo_m3;
}

function m3haDe(t: AguaTurno, serie: SerieAgua): number | null {
  if (serie === "real") return t.real_m3ha ?? (t.estado_riego === "aplicado" ? t.aplicado_m3ha : null);
  if (serie === "provisional") return t.estado_riego === "provisional" ? t.aplicado_m3ha : null;
  return serie === "propuesto" ? t.propuesto_m3ha : t.modelo_m3ha;
}

/**
 * Valor de una serie para un grupo de turnos: en m³ se suman; en m³/ha es el total de m³ dividido
 * por la superficie de los turnos que tienen dato (un turno solo: su m³/ha tal cual).
 */
export function valorAgua(turnos: AguaTurno[], serie: SerieAgua, unidad: UnidadAgua): number | null {
  if (unidad === "m3ha" && turnos.length === 1) return redondear(m3haDe(turnos[0], serie), 2);
  let m3 = 0;
  let area = 0;
  let hay = false;
  for (const t of turnos) {
    const v = m3De(t, serie);
    if (v == null) continue;
    hay = true;
    m3 += v;
    area += t.area_ha;
  }
  if (!hay) return null;
  return unidad === "m3" ? redondear(m3, 1) : area > 0 ? redondear(m3 / area, 2) : null;
}

/**
 * Partes de la barra apilada (real + provisional) del gráfico. En m³/ha las dos se dividen por la
 * misma superficie (turnos con riego real o provisional), así la barra suma la lámina del día; con
 * promedios separados, un día a medias sumaría dos promedios y saldría casi el doble.
 */
export function valorApilado(turnos: AguaTurno[], serie: "real" | "provisional", unidad: UnidadAgua): number | null {
  if (unidad === "m3" || turnos.length === 1) return valorAgua(turnos, serie, unidad);
  let m3 = 0;
  let area = 0;
  let hay = false;
  for (const t of turnos) {
    const real = m3De(t, "real");
    const provisional = m3De(t, "provisional");
    if (real == null && provisional == null) continue;
    area += t.area_ha;
    const v = serie === "real" ? real : provisional;
    if (v != null) { hay = true; m3 += v; }
  }
  return hay && area > 0 ? redondear(m3 / area, 2) : null;
}

function redondear(v: number | null, decimales: number): number | null {
  if (v == null || !Number.isFinite(v)) return null;
  const f = 10 ** decimales;
  return Math.round(v * f) / f;
}

/** Un punto del tooltip de ECharts (``trigger: "axis"``). */
export interface PuntoTooltip { seriesIndex?: number; dataIndex?: number; seriesName?: string; value?: unknown; marker?: unknown; axisValueLabel?: string }

const escapar = (s: string) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);

/**
 * Tooltip del gráfico de agua: día y alcance, cada serie con su unidad (sin las vacías) y, si el día
 * ya es todo real, cuánto se apartó lo regado del plan publicado. Series: 0 real, 1 provisional,
 * 2 publicado, 3 modelo. ``versiones`` (serie -> número) nombra la versión del cronograma de cada línea.
 */
export function tooltipAgua(puntos: PuntoTooltip[], unidad: UnidadAgua, alcance: string,
  versiones: Partial<Record<number, number | null>> = {}): string {
  const u = unidad === "m3ha" ? "m³/ha" : "m³";
  const d = unidad === "m3ha" ? 2 : 1;
  const fmt = new Intl.NumberFormat("es-PE", { minimumFractionDigits: d, maximumFractionDigits: d });
  const valor = (i: number) => {
    const v = puntos.find((p) => p.seriesIndex === i)?.value;
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  };
  const filas = puntos.filter((p) => valor(p.seriesIndex ?? -1) != null).map((p) =>
    `<div style="display:flex;justify-content:space-between;gap:16px"><span>${typeof p.marker === "string" ? p.marker : ""}` +
    `${escapar(p.seriesName ?? "")}${versiones[p.seriesIndex ?? -1] != null ? ` · v${versiones[p.seriesIndex ?? -1]}` : ""}</span><strong>${fmt.format(p.value as number)} ${u}</strong></div>`);
  let html = `<div style="margin-bottom:4px"><strong>${escapar(puntos[0]?.axisValueLabel ?? "")}</strong> · ${escapar(alcance)}</div>`;
  html += filas.length ? filas.join("") : "<div>Sin riego registrado</div>";
  const real = valor(0), provisional = valor(1);
  if (real != null && provisional != null) {
    html += `<div style="margin-top:4px;display:flex;justify-content:space-between;gap:16px"><span>Total del día</span>` +
      `<strong>${fmt.format(real + provisional)} ${u}</strong></div>`;
  }
  const dif = provisional == null ? diferenciaPct(real, valor(2)) : null;
  if (dif != null) {
    html += `<div style="margin-top:4px;color:#5F5849">Real vs publicado: ${dif > 0 ? "+" : ""}${new Intl.NumberFormat("es-PE", { maximumFractionDigits: 1 }).format(dif)} %</div>`;
  }
  return html;
}

/** Diferencia porcentual de `valor` respecto de `base` (null si falta alguno o la base es 0). */
export function diferenciaPct(valor: number | null, base: number | null): number | null {
  if (valor == null || base == null || base === 0) return null;
  return Math.round(((valor - base) / base) * 1000) / 10;
}

export function turnosElegidos(dia: AguaDia, turno: string): AguaTurno[] {
  return dia.turnos.filter((t) => turno === "todos" || String(t.turno_id) === turno);
}

/** Estado del riego real de un grupo: todos con dato real, algunos, solo provisional o nada. */
export function estadoReal(turnos: AguaTurno[]): "real" | "parcial" | "provisional" | "sin_dato" {
  const reales = turnos.filter((t) => m3De(t, "real") != null).length;
  if (reales === turnos.length && reales > 0) return "real";
  if (reales > 0) return "parcial";
  return turnos.some((t) => t.estado_riego === "provisional") ? "provisional" : "sin_dato";
}

/** Texto libre en una celda: sin fórmulas al abrirlo en Excel. */
const textoSeguro = (texto: string) => (/^[=+\-@\t\r]/.test(texto) ? `'${texto}` : texto);

const numeroCsv = (v: number | null) => (v == null ? "" : String(v).replace(".", ","));

/** CSV (separador «;» y coma decimal, como lo abre Excel en español) de días y turnos. */
export function csvAgua(dias: AguaDia[], unidad: UnidadAgua, conModelo: boolean): string {
  const u = unidad === "m3ha" ? "m3/ha" : "m3";
  const cabecera = ["Fecha", "Turno", ...(conModelo ? [`Modelo (${u})`] : []), `Modificado / publicado (${u})`,
    `Real (${u})`, "Real vs publicado (%)", ...(conModelo ? ["Real vs modelo (%)"] : []), "Estado del riego", "Hubo cambios", "Motivo"];
  const filas = [cabecera];
  for (const d of dias) {
    for (const t of d.turnos) {
      const prop = valorAgua([t], "propuesto", unidad);
      const real = valorAgua([t], "real", unidad);
      const modelo = valorAgua([t], "modelo", unidad);
      filas.push([
        d.fecha, t.turno_codigo, ...(conModelo ? [numeroCsv(modelo)] : []), numeroCsv(prop), numeroCsv(real),
        numeroCsv(diferenciaPct(real, prop)), ...(conModelo ? [numeroCsv(diferenciaPct(real, modelo))] : []),
        t.estado_riego === "aplicado" ? "Real" : t.estado_riego === "provisional" ? "Provisional" : "Sin dato",
        t.modificado ? "Sí" : "No", t.modificado ? textoSeguro(d.motivo ?? "") : "",
      ]);
    }
  }
  return "﻿" + filas.map((f) => f.map((c) => (/[;"\n]/.test(c) ? `"${c.replace(/"/g, '""')}"` : c)).join(";")).join("\r\n");
}
