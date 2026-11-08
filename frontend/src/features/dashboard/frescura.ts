import type { TonoBadge } from "../../components/ui/Badge";
import { diasEntre, formatearDiaCorto, sumarDias } from "../../lib/fechas";
import type { EstadoIngesta, FuenteFrescura, Frescura, IngestaCorrida } from "../../services/datos";

/** Nombres de las fuentes (frescura e ingestas) en lenguaje de usuario. */
const NOMBRE_FUENTE: Record<string, string> = {
  riego_aplicado: "Riego aplicado",
  riego_provisional: "Riego provisional",
  weatherlink: "WeatherLink (clima)",
  meteo: "WeatherLink (clima)",
  phytech: "Phytech",
  phytech_suelo: "Phytech suelo",
  phytech_planta: "Phytech planta",
  ndvi: "NDVI",
  phytech_ndvi: "NDVI",
  pronostico: "Pronóstico Phytech",
  phytech_pronostico: "Pronóstico Phytech",
  // Corridas de la carga histórica (CLI cargar-historico) y del reproceso (CLI reprocesar-weatherlink).
  historico_meteo: "Carga histórica: clima",
  historico_phytech: "Carga histórica: Phytech",
  historico_ndvi: "Carga histórica: NDVI",
  historico_riego: "Carga histórica: riego",
  reprocesar_weatherlink: "Reproceso WeatherLink",
};

/** Orden de las filas del panel (las desconocidas, al final). */
const ORDEN_FUENTE = [
  "riego_aplicado",
  "riego_provisional",
  "weatherlink",
  "phytech_suelo",
  "phytech_planta",
  "ndvi",
  "pronostico",
];

export function nombreFuente(fuente: string, nombre?: string | null): string {
  if (NOMBRE_FUENTE[fuente]) return NOMBRE_FUENTE[fuente];
  if (nombre) return nombre;
  const texto = fuente.replace(/_/g, " ").trim();
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

export function ordenarFuentes(fuentes: FuenteFrescura[]): FuenteFrescura[] {
  const pos = (f: FuenteFrescura) => {
    const i = ORDEN_FUENTE.indexOf(f.fuente);
    return i === -1 ? ORDEN_FUENTE.length : i;
  };
  return [...fuentes].sort((a, b) => pos(a) - pos(b));
}

export function esInformativa(f: FuenteFrescura): boolean {
  return f.informativa === true || f.estado === "informativo";
}

/** Día de referencia de la frescura: el que manda el backend o D-1 respecto de `fecha`. */
export function referenciaFrescura(frescura: Pick<Frescura, "fecha" | "referencia">): string {
  return frescura.referencia ?? sumarDias(frescura.fecha, -1);
}

/** Días de atraso de una fuente respecto de la referencia (0 si está al día; null sin datos). */
export function diasAtraso(f: FuenteFrescura, referencia: string): number | null {
  if (!f.ultima_fecha) return null;
  return Math.max(0, diasEntre(f.ultima_fecha.slice(0, 10), referencia));
}

export interface ResumenFrescura {
  /** Fuentes no informativas en naranja. */
  atrasadas: number;
  /** Fuentes (cualquiera) con huecos intermedios. */
  conHuecos: number;
  alDia: boolean;
}

export function resumirFrescura(fuentes: FuenteFrescura[]): ResumenFrescura {
  const atrasadas = fuentes.filter((f) => !esInformativa(f) && f.estado !== "verde").length;
  const conHuecos = fuentes.filter((f) => (f.huecos?.length ?? 0) > 0).length;
  return { atrasadas, conHuecos, alDia: atrasadas === 0 && conHuecos === 0 };
}

/**
 * Líneas por turno de una fuente de riego: solo lo que la fila de la fuente no dice ya.
 * - Un turno con otra última fecha que la mayoría: «TE05: hasta mié 04/11» (o «sin datos»).
 * - Un turno con huecos que no comparten todos los turnos: «TE05: falta mar 03/11».
 * Si todos los turnos están igual (misma fecha y mismos huecos), no devuelve nada.
 */
export function detalleTurnos(f: Pick<FuenteFrescura, "por_turno">): string[] {
  const turnos = f.por_turno ?? [];
  if (turnos.length === 0) return [];
  const frecuencia = new Map<string | null, number>();
  for (const t of turnos) frecuencia.set(t.ultima_fecha, (frecuencia.get(t.ultima_fecha) ?? 0) + 1);
  let masComun: string | null = turnos[0].ultima_fecha;
  for (const [fecha, n] of frecuencia) if (n > (frecuencia.get(masComun) ?? 0)) masComun = fecha;
  const comunes = new Set((turnos[0].huecos ?? []).filter((h) => turnos.every((t) => (t.huecos ?? []).includes(h))));

  const lineas: string[] = [];
  for (const t of turnos) {
    const partes: string[] = [];
    if (t.ultima_fecha !== masComun) {
      partes.push(t.ultima_fecha ? `hasta ${formatearDiaCorto(t.ultima_fecha)}` : "sin datos");
    }
    const propios = (t.huecos ?? []).filter((h) => !comunes.has(h)).sort();
    if (propios.length > 0) {
      const muestra = propios.slice(0, 3).map((h) => formatearDiaCorto(h)).join(", ");
      const resto = propios.length > 3 ? ` y ${propios.length - 3} más` : "";
      partes.push(`falta${propios.length === 1 ? "" : "n"} ${muestra}${resto}`);
    }
    if (partes.length > 0) lineas.push(`${t.turno_codigo}: ${partes.join(" · ")}`);
  }
  return lineas;
}

// ---------------------------------------------------------------------------
// Ingestas
// ---------------------------------------------------------------------------

export const ETIQUETA_ESTADO_INGESTA: Record<EstadoIngesta, string> = {
  en_curso: "En curso",
  ok: "Correcta",
  parcial: "Parcial",
  error: "Error",
};

export const TONO_ESTADO_INGESTA: Record<EstadoIngesta, TonoBadge> = {
  en_curso: "info",
  ok: "exito",
  parcial: "aviso",
  error: "error",
};

/** Mismo umbral que MINUTOS_SIN_LATIDO del backend; sin latido se usa el inicio. */
export const MINUTOS_SIN_LATIDO = 10;

export function corridaColgada(c: Pick<IngestaCorrida, "estado" | "inicio_at" | "latido_at">, ahora: Date = new Date()): boolean {
  if (c.estado !== "en_curso") return false;
  const ultimoLatido = Date.parse(c.latido_at ?? c.inicio_at);
  return Number.isFinite(ultimoLatido) && ahora.getTime() - ultimoLatido > MINUTOS_SIN_LATIDO * 60_000;
}

/** Corrida realmente en curso: «en_curso» y no colgada. */
export function corridaActiva(c: Pick<IngestaCorrida, "estado" | "inicio_at" | "latido_at">, ahora: Date = new Date()): boolean {
  return c.estado === "en_curso" && !corridaColgada(c, ahora);
}

/** Hay alguna corrida activa (las colgadas no cuentan: no bloquean ni mantienen el sondeo). */
export function hayIngestaEnCurso(corridas: IngestaCorrida[] | undefined, ahora: Date = new Date()): boolean {
  return !!corridas?.some((c) => corridaActiva(c, ahora));
}

/**
 * Corridas a mostrar: primero las «en_curso» (activas o colgadas), aunque no estén entre las más
 * recientes, para que siempre se vea por qué el panel dice «Actualizando…» o qué quedó sin terminar.
 */
export function corridasVisibles(corridas: IngestaCorrida[], cantidad: number): IngestaCorrida[] {
  const enCurso = corridas.filter((c) => c.estado === "en_curso");
  const resto = corridas.filter((c) => c.estado !== "en_curso");
  return [...enCurso, ...resto].slice(0, Math.max(cantidad, enCurso.length));
}

export interface ProgresoIngesta {
  total: number;
  terminadas: number;
  /** true cuando todas las corridas lanzadas terminaron (o no se encontraron tras terminar). */
  completo: boolean;
  /** Resultado global al completar: ok si todas ok, error si todas error, si no parcial. */
  resultado: "ok" | "parcial" | "error" | null;
}

/** Avance de las corridas lanzadas con «Actualizar ahora», según la última lista de `GET /ingestas`. */
export function progresoIngesta(lanzadas: number[], corridas: IngestaCorrida[], ahora: Date = new Date()): ProgresoIngesta {
  const porId = new Map(corridas.map((c) => [c.id, c]));
  const propias = lanzadas.map((id) => porId.get(id)).filter((c): c is IngestaCorrida => !!c);
  // Una corrida colgada (proceso muerto) cuenta como terminada con error: el sondeo no sigue para siempre.
  const terminadas = propias.filter((c) => !corridaActiva(c, ahora));
  const total = lanzadas.length;
  // Una corrida lanzada que ya no aparece en la lista cuenta como terminada solo si no queda
  // ninguna en curso (así el sondeo nunca queda colgado).
  const faltan = total - propias.length;
  const completo =
    total > 0 && terminadas.length === propias.length && (faltan === 0 || !hayIngestaEnCurso(corridas, ahora));
  let resultado: ProgresoIngesta["resultado"] = null;
  if (completo) {
    const estado = (c: IngestaCorrida) => (corridaColgada(c, ahora) ? "error" : c.estado);
    if (terminadas.length > 0 && terminadas.every((c) => estado(c) === "ok")) resultado = "ok";
    else if (terminadas.length > 0 && terminadas.every((c) => estado(c) === "error")) resultado = "error";
    else resultado = "parcial";
  }
  return { total, terminadas: completo ? total : terminadas.length, completo, resultado };
}

export function formatearDuracionMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${s % 60} s`;
}

export function etiquetaDisparo(c: Pick<IngestaCorrida, "disparo" | "usuario">): string {
  if (c.disparo === "programado") return "Programada";
  if (c.disparo === "script") return "Script";
  return c.usuario ? `Manual · ${c.usuario}` : "Manual";
}
