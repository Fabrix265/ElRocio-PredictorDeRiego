import { AlertTriangle, Clock, RefreshCw } from "lucide-react";

import { Badge, type TonoBadge } from "../../components/ui/Badge";
import type { AccionDia, EstadoCronograma, OrigenVersion } from "../../services/cronogramas";

export const ETIQUETA_ESTADO: Record<EstadoCronograma, string> = {
  borrador: "Borrador",
  publicado: "Publicado",
  visto: "Visto",
  correccion_solicitada: "Corrección solicitada",
};

export const TONO_ESTADO: Record<EstadoCronograma, TonoBadge> = {
  borrador: "neutro",
  publicado: "info",
  visto: "exito",
  correccion_solicitada: "aviso",
};

export const ETIQUETA_ORIGEN_VERSION: Record<OrigenVersion, string> = {
  modelo: "Propuesta del modelo",
  regenerado: "Regenerado",
  correccion: "Corrección",
  edicion: "Edición",
};

export const ETIQUETA_ACCION: Record<AccionDia, string> = {
  creado: "Creado",
  regenerado: "Regenerado",
  omitido: "Omitido",
};

export const TONO_ACCION: Record<AccionDia, TonoBadge> = {
  creado: "exito",
  regenerado: "info",
  omitido: "neutro",
};

export const AYUDA_MARCA = {
  preliminar:
    "Preliminar: es el día 2 o siguiente de la generación, el día anterior aún no terminó o usó un riego que no está registrado (cronograma o predicción).",
  datos_incompletos:
    "Datos incompletos: al generar, alguna fuente no tenía el día anterior o había huecos de riego en la última semana.",
  regenerado: "Regenerado: versión recalculada con el modelo sobre una anterior.",
  desactualizado:
    "Desactualizado: llegaron datos de riego o de clima/suelo/planta después de generar esta versión. Conviene regenerar.",
} as const;

interface Marcas {
  preliminar?: boolean | null;
  datos_incompletos?: boolean | null;
  regenerado?: boolean | null;
  desactualizado?: boolean | null;
}

/**
 * Marcas de calidad de una versión (§3.3), con el texto de ayuda en el title. Si se pasa `origen`
 * y ya es «regenerado», no se repite la marca «Regenerado» (el texto de la versión ya lo dice).
 */
export function MarcasVersion({ marcas, className, origen }: { marcas: Marcas; className?: string; origen?: OrigenVersion }) {
  const lista: { clave: keyof typeof AYUDA_MARCA; texto: string; tono: TonoBadge; icono?: React.ReactNode }[] = [];
  if (marcas.desactualizado) lista.push({ clave: "desactualizado", texto: "Desactualizado", tono: "aviso", icono: <RefreshCw /> });
  if (marcas.datos_incompletos) lista.push({ clave: "datos_incompletos", texto: "Datos incompletos", tono: "aviso", icono: <AlertTriangle /> });
  if (marcas.preliminar) lista.push({ clave: "preliminar", texto: "Preliminar", tono: "info", icono: <Clock /> });
  if (marcas.regenerado && origen !== "regenerado") lista.push({ clave: "regenerado", texto: "Regenerado", tono: "neutro" });
  if (lista.length === 0) return null;
  return (
    <ul className={className ?? "flex flex-wrap gap-1.5"} aria-label="Marcas de la versión">
      {lista.map((m) => (
        <li key={m.clave} title={AYUDA_MARCA[m.clave]}>
          <Badge tono={m.tono} icono={m.icono}>
            {m.texto}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

const fmt1 = new Intl.NumberFormat("es-PE", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const fmt2 = new Intl.NumberFormat("es-PE", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

export const formato = {
  m3ha: (v: number | null | undefined) => (v == null ? "—" : fmt2.format(v)),
  m3: (v: number | null | undefined) => (v == null ? "—" : fmt1.format(v)),
  min: (v: number | null | undefined) => (v == null ? "—" : `${fmt1.format(v)} min`),
  eto: (v: number | null | undefined) => (v == null ? "—" : fmt1.format(v)),
};

/**
 * Nombre legible del modelo: "2026-11-21_rf_total" → "21/11/2026" (fecha de entrenamiento).
 * Si el nombre no empieza con una fecha, se devuelve tal cual.
 */
export function fechaModelo(nombre: string | null | undefined): string {
  if (!nombre) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(nombre);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : nombre;
}

/** "3,227.7 m³ · 51.37 m³/ha" (vacío si no hay m³). */
export function textoAgua(m3: number | null | undefined, m3ha: number | null | undefined): string {
  return m3 == null ? "" : `${formato.m3(m3)} m³ · ${formato.m3ha(m3ha)} m³/ha`;
}

/** Totales del plan: m³, minutos y m³/ha = m³ ÷ hectáreas de los turnos que riegan. */
export function totalesPlan(turnos: { area_ha: number; ciclos: { riego_m3: number; duracion_min: number }[] }[]) {
  let m3 = 0, min = 0, area = 0;
  for (const t of turnos) {
    if (!t.ciclos.length) continue;
    area += t.area_ha;
    for (const c of t.ciclos) { m3 += c.riego_m3; min += c.duracion_min; }
  }
  return { m3, min, m3ha: area > 0 ? m3 / area : null };
}

/** "07:48" a partir de minutos desde las 00:00 (sin días). */
export function minutosAHora(min: number | null | undefined): string {
  if (min == null || !Number.isFinite(min)) return "—";
  const total = Math.floor(min) % 1440;
  return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
}
