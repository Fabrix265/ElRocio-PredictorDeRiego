import type { TonoBadge } from "../../components/ui/Badge";
import { diasEntre, sumarDias } from "../../lib/fechas";
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

export function hayIngestaEnCurso(corridas: IngestaCorrida[] | undefined): boolean {
  return !!corridas?.some((c) => c.estado === "en_curso");
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
export function progresoIngesta(lanzadas: number[], corridas: IngestaCorrida[]): ProgresoIngesta {
  const porId = new Map(corridas.map((c) => [c.id, c]));
  const propias = lanzadas.map((id) => porId.get(id)).filter((c): c is IngestaCorrida => !!c);
  const terminadas = propias.filter((c) => c.estado !== "en_curso");
  const total = lanzadas.length;
  // Una corrida lanzada que ya no aparece en la lista cuenta como terminada solo si no queda
  // ninguna en curso (así el sondeo nunca queda colgado).
  const faltan = total - propias.length;
  const completo =
    total > 0 && terminadas.length === propias.length && (faltan === 0 || !hayIngestaEnCurso(corridas));
  let resultado: ProgresoIngesta["resultado"] = null;
  if (completo) {
    if (terminadas.length > 0 && terminadas.every((c) => c.estado === "ok")) resultado = "ok";
    else if (terminadas.length > 0 && terminadas.every((c) => c.estado === "error")) resultado = "error";
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
