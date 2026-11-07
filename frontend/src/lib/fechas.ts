/**
 * Fechas siempre mostradas en hora de Lima (America/Lima, UTC-5 sin horario de verano),
 * sin importar la zona del navegador.
 */
export const ZONA_LIMA = "America/Lima";
const LOCALE = "es-PE";

const fmtFechaHora = new Intl.DateTimeFormat(LOCALE, {
  timeZone: ZONA_LIMA,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

const fmtFecha = new Intl.DateTimeFormat(LOCALE, {
  timeZone: ZONA_LIMA,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

const fmtFechaLarga = new Intl.DateTimeFormat(LOCALE, {
  timeZone: ZONA_LIMA,
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});

const fmtPartes = new Intl.DateTimeFormat("en-CA", {
  timeZone: ZONA_LIMA,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  hourCycle: "h23",
});

function aDate(valor: string | Date): Date | null {
  const d = typeof valor === "string" ? new Date(valor) : valor;
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "07/11/2026 06:15" en hora de Lima. Cadena vacía o inválida → "—". */
export function formatearFechaHora(valor: string | Date | null | undefined): string {
  if (!valor) return "—";
  const d = aDate(valor);
  return d ? fmtFechaHora.format(d).replace(",", "") : "—";
}

/** "07/11/2026" en hora de Lima. */
export function formatearFecha(valor: string | Date | null | undefined): string {
  if (!valor) return "—";
  const d = aDate(valor);
  return d ? fmtFecha.format(d) : "—";
}

/** "Sábado, 7 de noviembre de 2026" en hora de Lima. */
export function formatearFechaLarga(valor: string | Date = new Date()): string {
  const d = aDate(valor);
  if (!d) return "—";
  const texto = fmtFechaLarga.format(d);
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

function partesLima(ahora: Date) {
  const p = Object.fromEntries(fmtPartes.formatToParts(ahora).map((x) => [x.type, x.value]));
  return { anio: p.year, mes: p.month, dia: p.day, hora: Number(p.hour) };
}

/** Fecha de hoy en Lima como "AAAA-MM-DD". */
export function hoyLima(ahora: Date = new Date()): string {
  const { anio, mes, dia } = partesLima(ahora);
  return `${anio}-${mes}-${dia}`;
}

/** Hora (0–23) actual en Lima. */
export function horaLima(ahora: Date = new Date()): number {
  return partesLima(ahora).hora;
}

/** Saludo según la hora de Lima. */
export function saludoLima(ahora: Date = new Date()): string {
  const h = horaLima(ahora);
  if (h < 12) return "Buenos días";
  if (h < 19) return "Buenas tardes";
  return "Buenas noches";
}

/**
 * Convierte un día de calendario de Lima ("AAAA-MM-DD") en el instante ISO 8601 con zona
 * del inicio o del fin de ese día, para filtros de rango (contrato: fechas con zona).
 */
export function limiteDiaLima(fecha: string, limite: "inicio" | "fin"): string {
  return limite === "inicio" ? `${fecha}T00:00:00-05:00` : `${fecha}T23:59:59.999-05:00`;
}
