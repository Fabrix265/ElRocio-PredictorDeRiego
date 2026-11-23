import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Field } from "../../components/ui/Field";
import { Select } from "../../components/ui/Select";
import { Skeleton } from "../../components/ui/Skeleton";
import { formatearDiaCorto, formatearFechaHora } from "../../lib/fechas";
import { claveCronogramas, cronogramasApi, type CronogramaDetalle, type VersionResumen } from "../../services/cronogramas";
import { diferenciaPct } from "../datos/agua";
import { mensajeDeError } from "../../services/httpClient";
import { formato, minutosAHora } from "./etiquetas";

const CELDA = "border-b border-borde p-2 text-left";
const CAMPOS: Record<string, string> = { n_ciclos: "N.º de ciclos", ciclo: "Ciclo", riego_m3ha: "m³/ha", hora_inicio: "Inicio", inicio_min: "Inicio", duracion_min: "Duración (min)", duracion_manual: "Duración manual", riego_m3: "m³", fin_min: "Fin" };
function valor(campo: string, v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "boolean") return v ? "Sí" : "No";
  if (typeof v === "object") return Object.entries(v).map(([k, x]) => `${CAMPOS[k] ?? k}: ${valor(k, x)}`).join(" · ");
  if (["hora_inicio", "inicio_min", "fin_min"].includes(campo) && typeof v === "number") return `${minutosAHora(v)}${v >= 1440 ? " (+1 día)" : ""}`;
  return String(v);
}

export function Diferencias({ id, base, contra }: { id: number; base: number; contra: number }) {
  const q = useQuery({ queryKey: claveCronogramas.diferencias(id, base, contra), queryFn: ({ signal }) => cronogramasApi.diferencias(id, base, contra, signal) });
  if (q.isPending) return <Skeleton className="h-28" />;
  if (q.isError) return <Alert tono="error">{mensajeDeError(q.error)} <Button variante="fantasma" disabled={q.isFetching} onClick={() => void q.refetch()}>Reintentar</Button></Alert>;
  if (!q.data.cambios.length) return <p className="p-3 text-sm text-texto-2">Sin diferencias entre v{base} y v{contra}.</p>;
  return <div className="max-w-full overflow-x-auto"><table className="w-full min-w-[500px] text-sm">
    <caption className="sr-only">Comparación de v{base} con v{contra}</caption>
    <thead className="bg-hundido"><tr>{["Turno", "Ciclo", "Campo", `Antes (v${base}) → Después (v${contra})`].map((s) => <th key={s} className={CELDA}>{s}</th>)}</tr></thead>
    <tbody>{q.data.cambios.map((c, i) => <tr key={i}><td className={CELDA}>{c.turno_codigo}</td><td className={CELDA}>{c.ciclo ?? "—"}</td><td className={CELDA}>{CAMPOS[c.campo] ?? c.campo}</td><td className={`${CELDA} bg-activo-bg break-words`}><del className="text-texto-2">{valor(c.campo, c.antes)}</del> → {valor(c.campo, c.despues)}</td></tr>)}</tbody>
  </table></div>;
}

/** Total del día de dos versiones lado a lado: m³ y m³/ha, con la diferencia. */
export function TotalesComparados({ versiones, base, contra }: { versiones: VersionResumen[]; base: number; contra: number }) {
  const a = versiones.find((v) => v.numero === base);
  const b = versiones.find((v) => v.numero === contra);
  if (a?.total_m3 == null || b?.total_m3 == null) return null;
  const filas: [string, number | null | undefined, number | null | undefined, (v: number | null | undefined) => string][] = [
    ["Agua total (m³)", a.total_m3, b.total_m3, formato.m3],
    ["Lámina (m³/ha)", a.total_m3ha, b.total_m3ha, formato.m3ha],
  ];
  const NUM = `${CELDA} text-right tabular-nums`;
  return <div className="max-w-full overflow-x-auto"><table className="w-full min-w-[420px] text-sm">
    <caption className="sr-only">Total del día en v{base} y v{contra}</caption>
    <thead className="bg-hundido"><tr>
      <th className={CELDA}>Total del día</th><th className={`${CELDA} text-right`}>v{base}</th>
      <th className={`${CELDA} text-right`}>v{contra}</th><th className={`${CELDA} text-right`}>Diferencia</th>
    </tr></thead>
    <tbody>{filas.map(([etiqueta, x, y, fmt]) => {
      const dif = x != null && y != null ? y - x : null;
      const pct = diferenciaPct(y ?? null, x ?? null);
      return <tr key={etiqueta}>
        <th scope="row" className={`${CELDA} font-normal`}>{etiqueta}</th>
        <td className={NUM}>{fmt(x)}</td><td className={NUM}>{fmt(y)}</td>
        <td className={`${NUM} ${dif ? "font-semibold text-texto" : "text-texto-2"}`}>
          {dif == null ? "—" : `${dif > 0 ? "+" : ""}${fmt(dif)}`}{pct ? ` (${pct > 0 ? "+" : ""}${pct} %)` : ""}
        </td>
      </tr>;
    })}</tbody>
  </table></div>;
}

export function Comparador({ cronograma: c }: { cronograma: CronogramaDetalle }) {
  const [elegidas, setElegidas] = useState<{ base: number; contra: number } | null>(null);
  const base = elegidas?.base ?? c.versiones.find((v) => v.id === c.version_publicada_id)?.numero ?? c.versiones.at(-1)?.numero;
  const contra = elegidas?.contra ?? c.versiones.find((v) => v.id === c.borrador_version_id)?.numero ?? c.versiones[0]?.numero;
  const opciones = c.versiones.map((v) => ({ value: String(v.numero), label: `v${v.numero}` }));
  if (base == null || contra == null) return <p className="p-4 text-texto-2">Sin versiones para comparar.</p>;
  return <div className="flex min-w-0 flex-col gap-3 p-4">
    <div className="grid grid-cols-2 gap-3">
      <Field label="Comparar"><Select value={String(base)} opciones={opciones} onValueChange={(v) => setElegidas({ base: Number(v), contra })} /></Field>
      <Field label="Con"><Select value={String(contra)} opciones={opciones} onValueChange={(v) => setElegidas({ base, contra: Number(v) })} /></Field>
    </div>
    <TotalesComparados versiones={c.versiones} base={base} contra={contra} />
    <Diferencias id={c.id} base={base} contra={contra} />
  </div>;
}

const COLUMNAS_DATOS: [string, string][] = [
  ["eto_mm", "ETo (mm)"], ["t_media", "Temperatura media (°C)"], ["t_min", "Temperatura mínima (°C)"], ["t_max", "Temperatura máxima (°C)"],
  ["hr_media", "HR media (%)"], ["hr_min", "HR mínima (%)"], ["hr_max", "HR máxima (%)"], ["lluvia_mm", "Lluvia (mm)"],
  ["hum_zona_radicular_media", "Humedad radicular media (% vol.)"], ["hum_zona_radicular_cierre", "Humedad radicular al cierre (% vol.)"],
  ...[15, 30, 45, 60, 75, 90].flatMap((cm): [string, string][] => [
    [`hum_${cm}cm_media`, `Humedad a ${cm} cm, media (% vol.)`],
    [`hum_${cm}cm_cierre`, `Humedad a ${cm} cm, cierre (% vol.)`],
  ]),
  ["mds_contraccion_um", "MDS (µm)"],
];
/** Decimales fijos por columna: ETo 2, MDS 0, el resto 1 (columnas parejas, fáciles de comparar). */
const DECIMALES_DATOS: Record<string, number> = { eto_mm: 2, mds_contraccion_um: 0 };
const formatosDatos = new Map<number, Intl.NumberFormat>();
function cifraDato(campo: string, valor: number): string {
  const d = DECIMALES_DATOS[campo] ?? 1;
  if (!formatosDatos.has(d)) formatosDatos.set(d, new Intl.NumberFormat("es-PE", { minimumFractionDigits: d, maximumFractionDigits: d }));
  return formatosDatos.get(d)!.format(valor);
}

export function DatosCronograma({ id }: { id: number }) {
  const q = useQuery({ queryKey: claveCronogramas.datosCampo(id), queryFn: ({ signal }) => cronogramasApi.datosCampo(id, 7, signal) });
  if (q.isPending) return <Skeleton className="m-4 h-40" />;
  if (q.isError) return <Alert tono="error">{mensajeDeError(q.error)} <Button variante="fantasma" disabled={q.isFetching} onClick={() => void q.refetch()}>Reintentar</Button></Alert>;
  const columnas = COLUMNAS_DATOS.filter(([k]) => q.data.some((d) => d[k] != null));
  if (!q.data.length || !columnas.length) return <p className="p-4 text-texto-2">Sin datos de campo en los siete días previos.</p>;
  return <div className="min-w-0 p-4">
    <p className="mb-3 text-xs text-texto-2">Siete días previos al cronograma. Humedad volumétrica del suelo; HR: humedad relativa del aire.</p>
    <div className="max-w-full overflow-x-auto"><table className="w-full text-sm tabular-nums"><caption className="sr-only">Datos de campo por día</caption>
      <thead className="bg-hundido"><tr><th className={CELDA}>Día</th>{columnas.map(([k, s]) => <th key={k} className={`${CELDA} min-w-28`}>{s}</th>)}</tr></thead>
      <tbody>{q.data.map((d) => <tr key={d.fecha}><th className={`${CELDA} whitespace-nowrap`}>{formatearDiaCorto(d.fecha)}</th>{columnas.map(([k]) => <td key={k} className={CELDA}>{typeof d[k] === "number" ? cifraDato(k, d[k]) : d[k] == null ? "—" : String(d[k])}</td>)}</tr>)}</tbody>
    </table></div>
  </div>;
}

const EVENTOS: Record<string, string> = {
  generado: "Generado", regenerado: "Regenerado", corregido: "Corregido", borrador_descartado: "Borrador descartado",
  publicado: "Publicado", modificado: "Modificado", visto_programador: "Visto del programador", abierto_programador: "Abierto por el programador",
  visto_subgerente: "Revisado por el subgerente", correccion_solicitada: "Corrección solicitada", correccion_atendida: "Corrección atendida",
  correccion_mantenida: "Versión mantenida", riego_provisional_creado: "Riego provisional creado", riego_provisional_actualizado: "Riego provisional actualizado",
  riego_reemplazado_excel: "Riego reemplazado por Excel", riego_marcado_aplicado: "Riego marcado como aplicado", exportado: "Exportado",
};
export function LineaTiempo({ id }: { id: number }) {
  const q = useQuery({ queryKey: claveCronogramas.eventos(id), queryFn: ({ signal }) => cronogramasApi.eventos(id, signal) });
  if (q.isPending) return <Skeleton className="m-4 h-40" />;
  if (q.isError) return <Alert tono="error">{mensajeDeError(q.error)} <Button variante="fantasma" disabled={q.isFetching} onClick={() => void q.refetch()}>Reintentar</Button></Alert>;
  if (!q.data.length) return <p className="p-4 text-texto-2">Sin eventos registrados.</p>;
  return <ol className="m-4 flex flex-col gap-5 border-l border-borde pl-4">{q.data.map((e, i) => <li key={`${e.ocurrido_at}-${i}`} className="relative break-words">
    <span className="absolute top-1 -left-[21px] size-2 rounded-full bg-marca" aria-hidden="true" />
    <p className="text-sm font-semibold">{EVENTOS[e.tipo] ?? "Actividad del cronograma"}{e.version_numero != null && ` · v${e.version_numero}`}</p>
    <p className="text-xs text-texto-2"><time dateTime={e.ocurrido_at}>{formatearFechaHora(e.ocurrido_at)}</time> · {e.usuario ?? "Sistema"}</p>
    {(e.comentario || e.motivo_codigo) && <p className="mt-1 text-sm">{[e.motivo_codigo?.replaceAll("_", " "), e.comentario].filter(Boolean).join(" · ")}</p>}
  </li>)}</ol>;
}
