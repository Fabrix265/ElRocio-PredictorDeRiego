import { Moon } from "lucide-react";
import type { CSSProperties } from "react";

import { Badge } from "../../components/ui/Badge";
import { cn } from "../../lib/cn";
import { formatearDia, formatearDiaCorto } from "../../lib/fechas";
import type { RegistroRiego } from "../../services/riego";
import type { Turno } from "../catalogo/api";
import {
  ETIQUETA_ESTADO_CELDA,
  TONO_ESTADO_CELDA,
  estadoCelda,
  formatearM3,
  formatearM3ha,
  resumirCiclos,
} from "./etiquetas";

/** Clave de un turno-día en el mapa de registros. */
export function claveTurnoDia(turnoId: number, fecha: string): string {
  return `${turnoId}|${fecha}`;
}

export function indexarRegistros(registros: RegistroRiego[]): Map<string, RegistroRiego> {
  return new Map(registros.map((r) => [claveTurnoDia(r.turno_id, r.fecha), r]));
}

interface TablaRiegoProps {
  dias: string[];
  turnos: Turno[];
  registros: Map<string, RegistroRiego>;
  onSeleccionar: (turno: Turno, fecha: string, registro: RegistroRiego) => void;
  seleccionado?: string | null;
}

function Celda({
  turno,
  fecha,
  registro,
  onSeleccionar,
  seleccionada,
}: {
  turno: Turno;
  fecha: string;
  registro: RegistroRiego | undefined;
  onSeleccionar: TablaRiegoProps["onSeleccionar"];
  seleccionada: boolean;
}) {
  const estado = estadoCelda(registro);
  const resumen = resumirCiclos(registro?.ciclos);
  const etiqueta =
    `${turno.codigo}, ${formatearDia(fecha)}: ${ETIQUETA_ESTADO_CELDA[estado]}` +
    (resumen.n > 0 ? `, ${resumen.n} ${resumen.n === 1 ? "ciclo" : "ciclos"}, ${formatearM3ha(resumen.m3ha)} m³/ha` : "");

  const contenido = (
    <>
      <div className="flex flex-wrap items-center justify-between gap-1.5">
        <span className="text-xs font-semibold text-texto @3xl:hidden">{turno.codigo}</span>
        <Badge
          tono={TONO_ESTADO_CELDA[estado]}
          className={cn("max-w-full px-2", estado === "sin_registro" && "border-dashed bg-transparent text-texto-3")}
        >
          {ETIQUETA_ESTADO_CELDA[estado]}
        </Badge>
        {registro && registro.version > 1 && (
          <span className="text-[11px] text-texto-3" title="Versión del registro">
            v{registro.version}
          </span>
        )}
      </div>
      {resumen.n > 0 && (
        <>
          <p className="cifras text-[13px] font-semibold whitespace-nowrap text-texto">
            {formatearM3ha(resumen.m3ha)} <span className="text-[11px] font-normal text-texto-2">m³/ha</span>
          </p>
          <ul className="cifras flex flex-col gap-0.5 text-[11px] leading-4 text-texto-2" aria-label="Ciclos">
            {registro!.ciclos.map((c) => (
              <li key={c.inicio_min} className="flex items-center gap-1 whitespace-nowrap">
                {c.hora_inicio}–{c.hora_fin}
                {c.fin_dia_siguiente && (
                  <Moon className="size-3 text-texto-3" aria-label="termina al día siguiente" />
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );

  const clases = cn(
    "flex min-h-[64px] min-w-0 flex-col gap-1.5 rounded-md border px-2.5 py-2 text-left",
    estado === "aplicado" && "border-ok/25 bg-superficie",
    estado === "provisional" && "border-warn/40 bg-warn-bg/40",
    estado === "sin_riego" && "border-borde bg-hundido",
    estado === "sin_registro" && "border-dashed border-borde bg-transparent",
    seleccionada && "ring-2 ring-foco",
  );

  if (!registro) {
    return (
      <div className={clases} aria-label={etiqueta} role="group">
        {contenido}
      </div>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onSeleccionar(turno, fecha, registro)}
      aria-label={`Ver detalle: ${etiqueta}`}
      className={cn(
        clases,
        "cursor-pointer transition-colors hover:border-green-400 hover:bg-activo-bg focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-foco",
      )}
    >
      {contenido}
    </button>
  );
}

/**
 * Riego por día (filas, la más reciente arriba) × turno (columnas) con sus ciclos.
 * En celular cada día es una tarjeta con los turnos apilados (sin scroll horizontal).
 */
export function TablaRiego({ dias, turnos, registros, onSeleccionar, seleccionado }: TablaRiegoProps) {
  const estiloColumnas = { "--n": turnos.length } as CSSProperties;
  // Consulta de contenedor (no de pantalla): con la barra lateral abierta la tabla puede ser angosta.
  const columnas = "@3xl:grid-cols-[104px_repeat(var(--n),minmax(0,1fr))]";

  return (
    <div className="@container flex flex-col" style={estiloColumnas}>
      <div className={cn("hidden gap-2 border-b border-borde bg-hundido px-4 py-2 @3xl:grid", columnas)} aria-hidden="true">
        <span className="text-xs font-semibold text-texto-2">Fecha</span>
        {turnos.map((t) => (
          <span key={t.id} className="text-xs font-semibold text-texto-2">
            {t.codigo}
            <span className="ml-1 font-normal text-texto-3">{formatearM3ha(t.area_ha)} ha</span>
          </span>
        ))}
      </div>
      {dias.map((fecha) => {
        const delDia = turnos.map((t) => registros.get(claveTurnoDia(t.id, fecha)));
        const m3Dia = delDia.reduce((s, r) => s + resumirCiclos(r?.ciclos).m3, 0);
        const idTitulo = `dia-${fecha}`;
        return (
          <section
            key={fecha}
            aria-labelledby={idTitulo}
            className={cn("grid grid-cols-2 gap-2 border-b border-borde px-4 py-3 @lg:grid-cols-3", columnas)}
          >
            <div className="col-span-full flex items-baseline justify-between gap-2 @3xl:col-span-1 @3xl:flex-col @3xl:justify-start @3xl:gap-0.5">
              <h3 id={idTitulo} className="cifras text-[13px] font-semibold text-texto capitalize">
                {formatearDiaCorto(fecha)}
              </h3>
              <span className="cifras text-[11px] text-texto-3">{m3Dia > 0 ? `${formatearM3(m3Dia)} m³` : "—"}</span>
            </div>
            {turnos.map((t, i) => (
              <Celda
                key={t.id}
                turno={t}
                fecha={fecha}
                registro={delDia[i]}
                onSeleccionar={onSeleccionar}
                seleccionada={seleccionado === claveTurnoDia(t.id, fecha)}
              />
            ))}
          </section>
        );
      })}
    </div>
  );
}
