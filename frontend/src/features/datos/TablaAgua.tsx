import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import { Fragment, useState } from "react";
import { Link } from "react-router";

import { Badge, type TonoBadge } from "../../components/ui/Badge";
import { cn } from "../../lib/cn";
import { formatearDiaCorto } from "../../lib/fechas";
import type { AguaDia, AguaTurno } from "../../services/reportes";
import { diferenciaPct, estadoReal, turnosElegidos, valorAgua, type UnidadAgua } from "./agua";

const TH = "border-b border-borde bg-hundido px-2.5 py-2 text-xs font-semibold text-texto-2 whitespace-nowrap";
const TD = "border-b border-borde px-2.5 py-2 whitespace-nowrap";
const NUM = "text-right tabular-nums";
const formato = new Intl.NumberFormat("es-PE", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const formatoPct = new Intl.NumberFormat("es-PE", { minimumFractionDigits: 1, maximumFractionDigits: 1, signDisplay: "exceptZero" });
const cifra = (v: number | null) => (v == null ? "—" : formato.format(v));

const ESTADO: Record<ReturnType<typeof estadoReal>, [string, TonoBadge]> = {
  real: ["Real", "exito"],
  parcial: ["Real parcial", "aviso"],
  provisional: ["Provisional", "aviso"],
  sin_dato: ["Sin dato", "neutro"],
};

function Diferencia({ valor }: { valor: number | null }) {
  if (valor == null) return <span className="text-texto-3">—</span>;
  const fuerte = Math.abs(valor) >= 15;
  return <span className={cn(fuerte ? "font-semibold text-err-tx" : "text-texto")}>{formatoPct.format(valor)} %</span>;
}

function Celdas({ turnos, unidad, conModelo }: { turnos: AguaTurno[]; unidad: UnidadAgua; conModelo: boolean }) {
  const modelo = valorAgua(turnos, "modelo", unidad);
  const prop = valorAgua(turnos, "propuesto", unidad);
  const real = valorAgua(turnos, "real", unidad);
  const provisional = valorAgua(turnos, "provisional", unidad);
  return <>
    {conModelo && <td className={cn(TD, NUM)}>{cifra(modelo)}</td>}
    <td className={cn(TD, NUM)}>{cifra(prop)}</td>
    <td className={cn(TD, NUM)}>
      {cifra(real)}
      {real == null && provisional != null && <div className="text-xs text-texto-3">pendiente: {cifra(provisional)}</div>}
    </td>
    <td className={cn(TD, NUM)}><Diferencia valor={diferenciaPct(real, prop)} /></td>
    {conModelo && <td className={cn(TD, NUM)}><Diferencia valor={diferenciaPct(real, modelo)} /></td>}
  </>;
}

/**
 * Tabla por día (y, al desplegar, por turno): modelo, modificado/publicado, real y sus diferencias.
 * «Pendiente» es el riego provisional del cronograma mientras no llega el dato real del controlador.
 */
export function TablaAgua({ dias, unidad, conModelo, turno = "todos", desplegado = false, enlaces = true }: {
  dias: AguaDia[]; unidad: UnidadAgua; conModelo: boolean; turno?: string; desplegado?: boolean; enlaces?: boolean;
}) {
  const [abiertos, setAbiertos] = useState<Set<string>>(() => new Set(desplegado ? dias.map((d) => d.fecha) : []));
  const u = unidad === "m3ha" ? "m³/ha" : "m³";
  const ordenados = [...dias].sort((a, b) => b.fecha.localeCompare(a.fecha));
  const alternar = (fecha: string) => setAbiertos((prev) => {
    const nuevo = new Set(prev);
    if (nuevo.has(fecha)) nuevo.delete(fecha); else nuevo.add(fecha);
    return nuevo;
  });
  const columnas = 4 + (conModelo ? 2 : 0) + 2 + (enlaces ? 1 : 0);
  return (
    <div className="relative min-w-0 max-w-full overflow-x-auto">
      <table className="w-full min-w-[640px] border-collapse text-sm">
        <caption className="sr-only">Riego por día: modelo, modificado y real</caption>
        <thead>
          <tr>
            <th scope="col" className={cn(TH, "text-left")}>Día / turno</th>
            {conModelo && <th scope="col" className={cn(TH, "text-right")}>Modelo ({u})</th>}
            <th scope="col" className={cn(TH, "text-right")}>{conModelo ? "Modificado" : "Publicado"} ({u})</th>
            <th scope="col" className={cn(TH, "text-right")}>Real ({u})</th>
            <th scope="col" className={cn(TH, "text-right")}>Real vs {conModelo ? "modif." : "publ."}</th>
            {conModelo && <th scope="col" className={cn(TH, "text-right")}>Real vs modelo</th>}
            <th scope="col" className={cn(TH, "text-left")}>Riego</th>
            <th scope="col" className={cn(TH, "text-left")}>Cambios</th>
            {enlaces && <th scope="col" className={TH}><span className="sr-only">Cronograma</span></th>}
          </tr>
        </thead>
        <tbody>
          {ordenados.map((d) => {
            const turnos = turnosElegidos(d, turno);
            const abierto = abiertos.has(d.fecha);
            const [estado, tono] = ESTADO[estadoReal(turnos)];
            const modificado = turnos.some((t) => t.modificado);
            return (
              <Fragment key={d.fecha}>
                <tr className="bg-superficie">
                  <th scope="row" className={cn(TD, "text-left font-semibold text-texto")}>
                    <button type="button" onClick={() => alternar(d.fecha)} aria-expanded={abierto}
                      className="inline-flex items-center gap-1 rounded hover:text-marca focus-visible:outline-2 focus-visible:outline-foco">
                      {abierto ? <ChevronDown className="size-4" aria-hidden="true" /> : <ChevronRight className="size-4" aria-hidden="true" />}
                      {formatearDiaCorto(d.fecha)}
                    </button>
                  </th>
                  <Celdas turnos={turnos} unidad={unidad} conModelo={conModelo} />
                  <td className={TD}><Badge tono={tono}>{estado}</Badge></td>
                  <td className={cn(TD, "max-w-56 whitespace-normal")}>
                    {modificado ? <><Badge tono="info">Modificado</Badge>{d.motivo && <div className="mt-0.5 text-xs text-texto-2">{d.motivo}</div>}</>
                      : d.propuesta_version != null ? <span className="text-xs text-texto-2">Sin cambios</span>
                        : <span className="text-xs text-texto-3">Sin cronograma</span>}
                  </td>
                  {enlaces && <td className={cn(TD, "text-right")}>
                    {d.cronograma_id != null && <Link to={`/cronogramas/${d.cronograma_id}`} className="inline-flex items-center gap-1 text-xs font-semibold text-marca hover:underline">
                      v{d.propuesta_version ?? "—"} <ExternalLink className="size-3.5" aria-hidden="true" /><span className="sr-only">Ver cronograma del {formatearDiaCorto(d.fecha)}</span>
                    </Link>}
                  </td>}
                </tr>
                {abierto && turnos.map((t) => (
                  <tr key={`${d.fecha}-${t.turno_id}`} className="bg-hundido/40 text-[13px]">
                    <th scope="row" className={cn(TD, "pl-8 text-left font-normal text-texto")}>{t.turno_codigo}</th>
                    <Celdas turnos={[t]} unidad={unidad} conModelo={conModelo} />
                    <td className={cn(TD, "text-xs text-texto-2")}>{t.sin_riego ? "No se regó" : ESTADO[estadoReal([t])][0]}</td>
                    <td className={cn(TD, "text-xs")}>{t.modificado ? <span className="font-semibold text-info-tx">Cambió</span> : <span className="text-texto-3">—</span>}</td>
                    {enlaces && <td className={TD} />}
                  </tr>
                ))}
                {abierto && !turnos.length && <tr><td colSpan={columnas} className={cn(TD, "text-texto-3")}>Sin turnos.</td></tr>}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
