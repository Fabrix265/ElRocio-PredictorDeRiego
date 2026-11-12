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

const fmtFechaCorta = new Intl.DateTimeFormat(LOCALE, {
  timeZone: ZONA_LIMA,
  weekday: "short",
  day: "2-digit",
  month: "2-digit",
});

const fmtPartes = new Intl.DateTimeFormat("en-CA", {
  timeZone: ZONA_LIMA,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
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

/** "sáb 07/11" en hora de Lima (cabecera en pantallas medianas). */
export function formatearFechaCorta(valor: string | Date = new Date()): string {
  const d = aDate(valor);
  if (!d) return "—";
  const p = Object.fromEntries(fmtFechaCorta.formatToParts(d).map((x) => [x.type, x.value]));
  return `${p.weekday.replace(".", "")} ${p.day}/${p.month}`;
}

function partesLima(ahora: Date) {
  const p = Object.fromEntries(fmtPartes.formatToParts(ahora).map((x) => [x.type, x.value]));
  return { anio: p.year, mes: p.month, dia: p.day, hora: Number(p.hour), minuto: Number(p.minute) };
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

/** Minutos transcurridos desde las 00:00 de hoy en Lima (0–1439). */
export function minutoDelDiaLima(ahora: Date = new Date()): number {
  const { hora, minuto } = partesLima(ahora);
  return hora * 60 + minuto;
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

// ---------------------------------------------------------------------------
// Días de calendario ("AAAA-MM-DD"): fechas de riego, lecturas y frescura.
// No son instantes: se operan en UTC para que la zona del navegador nunca corra el día.
// ---------------------------------------------------------------------------

const RE_DIA = /^(\d{4})-(\d{2})-(\d{2})$/;
const DIAS_SEMANA = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];

function diaAUtc(fecha: string): Date | null {
  const m = RE_DIA.exec(fecha.slice(0, 10));
  if (!m) return null;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
  return Number.isNaN(d.getTime()) ? null : d;
}

function utcADia(d: Date): string {
  return d.toISOString().slice(0, 10);
}

/** true si es un día válido "AAAA-MM-DD". */
export function esDiaValido(fecha: string | null | undefined): fecha is string {
  if (!fecha) return false;
  const d = diaAUtc(fecha);
  return !!d && utcADia(d) === fecha.slice(0, 10);
}

/** Suma (o resta) días a un día de calendario. */
export function sumarDias(fecha: string, dias: number): string {
  const d = diaAUtc(fecha);
  if (!d) return fecha;
  d.setUTCDate(d.getUTCDate() + dias);
  return utcADia(d);
}

/** Días de `desde` a `hasta` (positivo si `hasta` es posterior). */
export function diasEntre(desde: string, hasta: string): number {
  const a = diaAUtc(desde);
  const b = diaAUtc(hasta);
  if (!a || !b) return 0;
  return Math.round((b.getTime() - a.getTime()) / 86_400_000);
}

/** Lista de días de `desde` a `hasta`, ambos incluidos (vacía si el rango está invertido). */
export function listaDias(desde: string, hasta: string): string[] {
  const n = diasEntre(desde, hasta);
  if (n < 0 || !esDiaValido(desde)) return [];
  return Array.from({ length: n + 1 }, (_, i) => sumarDias(desde, i));
}

/** "05/11/2026" a partir de "2026-11-05" (sin conversión de zona). */
export function formatearDia(fecha: string | null | undefined): string {
  if (!fecha) return "—";
  const d = diaAUtc(fecha);
  if (!d) return "—";
  const [a, m, dd] = utcADia(d).split("-");
  return `${dd}/${m}/${a}`;
}

/** "jue 05/11" a partir de "2026-11-05" (sin conversión de zona). */
export function formatearDiaCorto(fecha: string | null | undefined): string {
  if (!fecha) return "—";
  const d = diaAUtc(fecha);
  if (!d) return "—";
  const [, m, dd] = utcADia(d).split("-");
  return `${DIAS_SEMANA[d.getUTCDay()]} ${dd}/${m}`;
}
