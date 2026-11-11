import { ChevronLeft, ChevronRight, Moon } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Checkbox } from "../../components/ui/Checkbox";
import { cn } from "../../lib/cn";
import { formatearDiaCorto } from "../../lib/fechas";
import type { CambioAplicar, GrupoCarga, ResultadoCarga } from "../../services/riego";
import {
  DESCRIPCION_RESULTADO,
  ETIQUETA_RESULTADO,
  RESULTADOS,
  TONO_RESULTADO,
  cambiosParaResultado,
  contarResultados,
  esAplicable,
  estadoGrupo,
  etiquetaOrigen,
  formatearM3ha,
  resumirCiclos,
} from "./etiquetas";

export type FiltroDetalle = "cambios" | "todos" | ResultadoCarga;
const POR_PAGINA = 50;

export function filtrarGrupos(grupos: GrupoCarga[], filtro: FiltroDetalle): GrupoCarga[] {
  const filtrados =
    filtro === "todos" ? grupos : filtro === "cambios" ? grupos.filter((g) => g.resultado !== "igual") : grupos.filter((g) => g.resultado === filtro);
  // Más reciente primero; dentro del día, por turno.
  return [...filtrados].sort((a, b) =>
    a.fecha === b.fecha ? (a.turno_codigo ?? "").localeCompare(b.turno_codigo ?? "") : a.fecha < b.fecha ? 1 : -1,
  );
}

interface VistaPreviaProps {
  grupos: GrupoCarga[];
  /** Deshabilita las casillas (carga vencida o confirmando). */
  bloqueada: boolean;
  onCambiar: (cambios: CambioAplicar[]) => void;
}

function TarjetaResultado({
  resultado,
  total,
  aplicar,
  marcado,
  activo,
  bloqueada,
  onFiltrar,
  onMarcar,
}: {
  resultado: ResultadoCarga;
  total: number;
  aplicar: number;
  marcado: boolean | "mixto";
  activo: boolean;
  bloqueada: boolean;
  onFiltrar: () => void;
  onMarcar: (aplicar: boolean) => void;
}) {
  const aplicable = esAplicable({ resultado });
  return (
    <div
      className={cn(
        "flex min-w-0 flex-col gap-2 rounded-lg border bg-superficie px-3 py-2.5",
        activo ? "border-marca ring-1 ring-marca" : "border-borde",
      )}
    >
      <button
        type="button"
        onClick={onFiltrar}
        aria-pressed={activo}
        aria-label={`${ETIQUETA_RESULTADO[resultado]}: ${total}. Ver en el detalle`}
        title={DESCRIPCION_RESULTADO[resultado]}
        className="flex flex-col items-start gap-1 rounded text-left focus-visible:outline-2 focus-visible:outline-foco"
      >
        {/* En celular la tarjeta mide ~158 px: la etiqueta («Reemplaza provisional») hace salto de línea. */}
        <Badge tono={TONO_RESULTADO[resultado]} ajustar>
          {ETIQUETA_RESULTADO[resultado]}
        </Badge>
        <span className="cifras text-2xl leading-8 font-bold text-texto">{total.toLocaleString("es-PE")}</span>
      </button>
      {aplicable && total > 0 ? (
        <label className="flex items-center gap-2 text-xs text-texto-2">
          <Checkbox
            checked={marcado}
            disabled={bloqueada}
            onChange={() => onMarcar(marcado !== true)}
            aria-label={`Aplicar todos: ${ETIQUETA_RESULTADO[resultado]}`}
          />
          <span className="cifras">
            Aplicar {aplicar.toLocaleString("es-PE")} de {total.toLocaleString("es-PE")}
          </span>
        </label>
      ) : (
        <span className="text-xs text-texto-3">{resultado === "igual" ? "No crea versión" : resultado === "error" ? "No se aplica" : "—"}</span>
      )}
    </div>
  );
}

function FilaGrupo({ g, bloqueada, onCambiar }: { g: GrupoCarga; bloqueada: boolean; onCambiar: VistaPreviaProps["onCambiar"] }) {
  const r = resumirCiclos(g.ciclos);
  const aplicable = esAplicable(g);
  const turno = g.turno_codigo ?? "Turno desconocido";
  return (
    <li className="grid grid-cols-[auto_1fr] items-start gap-x-3 gap-y-1 border-b border-borde px-4 py-2.5 md:grid-cols-[24px_96px_88px_190px_1fr] md:items-center">
      <div className="row-span-3 pt-0.5 md:row-span-1 md:pt-0">
        {aplicable ? (
          <Checkbox
            checked={g.aplicar}
            disabled={bloqueada}
            onChange={() => onCambiar([{ id: g.id, aplicar: !g.aplicar }])}
            aria-label={`Aplicar ${turno} del ${formatearDiaCorto(g.fecha)}`}
          />
        ) : (
          <span className="block size-4" aria-hidden="true" />
        )}
      </div>
      <div className="flex items-center gap-2 md:contents">
        <span className="cifras text-[13px] font-medium capitalize">{formatearDiaCorto(g.fecha)}</span>
        <span className="text-[13px] font-semibold">{turno}</span>
      </div>
      <div className="md:order-none">
        <Badge tono={TONO_RESULTADO[g.resultado]}>{ETIQUETA_RESULTADO[g.resultado]}</Badge>
      </div>
      <div className="col-start-2 flex min-w-0 flex-col gap-0.5 md:col-start-auto">
        <span className="cifras text-xs text-texto">
          {g.resultado === "sin_riego"
            ? "Sin filas en el archivo: no se regó"
            : r.n === 0
              ? "—"
              : `${r.n} ${r.n === 1 ? "ciclo" : "ciclos"} · ${formatearM3ha(r.m3ha)} m³/ha · ${r.desde}–${r.hasta}`}
          {r.finDiaSiguiente && <Moon className="ml-1 inline size-3 text-texto-3" aria-label="termina al día siguiente" />}
        </span>
        {(g.vigente_estado || g.vigente_origen) && g.resultado !== "nuevo" && g.resultado !== "igual" && (
          <span className="text-[11px] text-texto-3">
            Vigente: {g.vigente_estado ?? "—"} · {etiquetaOrigen(g.vigente_origen)}
          </span>
        )}
        {(g.mensajes?.length ?? 0) > 0 && (
          <ul className={cn("text-[11px] leading-4", g.resultado === "error" ? "text-err-tx" : "text-texto-2")}>
            {g.mensajes!.map((m, i) => (
              <li key={i}>{m}</li>
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

/** Contadores por resultado (con casillas por grupo) y detalle por turno-día. */
export function VistaPreviaCarga({ grupos, bloqueada, onCambiar }: VistaPreviaProps) {
  const [filtro, setFiltro] = useState<FiltroDetalle>("cambios");
  const [pagina, setPagina] = useState(1);
  const contadores = useMemo(() => contarResultados(grupos), [grupos]);
  const filtrados = useMemo(() => filtrarGrupos(grupos, filtro), [grupos, filtro]);
  const totalPaginas = Math.max(1, Math.ceil(filtrados.length / POR_PAGINA));
  const paginaActual = Math.min(pagina, totalPaginas);
  const visibles = filtrados.slice((paginaActual - 1) * POR_PAGINA, paginaActual * POR_PAGINA);

  const cambiarFiltro = (f: FiltroDetalle) => {
    setFiltro((actual) => (actual === f && f !== "cambios" ? "cambios" : f));
    setPagina(1);
  };

  const OPCIONES: Array<{ valor: FiltroDetalle; etiqueta: string; n: number }> = [
    { valor: "cambios", etiqueta: "Con cambios", n: grupos.length - contadores.igual.total },
    { valor: "todos", etiqueta: "Todos", n: grupos.length },
  ];

  return (
    <div className="flex flex-col gap-4">
      <section aria-label="Resumen por resultado" className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {RESULTADOS.map((res) => (
          <TarjetaResultado
            key={res}
            resultado={res}
            total={contadores[res].total}
            aplicar={contadores[res].aplicar}
            marcado={estadoGrupo(grupos, res)}
            activo={filtro === res}
            bloqueada={bloqueada}
            onFiltrar={() => cambiarFiltro(res)}
            onMarcar={(aplicar) => {
              const cambios = cambiosParaResultado(grupos, res, aplicar);
              if (cambios.length) onCambiar(cambios);
            }}
          />
        ))}
      </section>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-borde px-4 py-3">
          <h2 className="text-[15px] font-semibold">Detalle por turno-día</h2>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filtrar detalle">
            {OPCIONES.map((o) => (
              <Button
                key={o.valor}
                tamano="sm"
                variante={filtro === o.valor ? "primario" : "secundario"}
                aria-pressed={filtro === o.valor}
                onClick={() => cambiarFiltro(o.valor)}
              >
                {o.etiqueta} <span className="cifras opacity-80">{o.n.toLocaleString("es-PE")}</span>
              </Button>
            ))}
            {filtro !== "cambios" && filtro !== "todos" && (
              <Badge tono={TONO_RESULTADO[filtro]}>Solo: {ETIQUETA_RESULTADO[filtro]}</Badge>
            )}
          </div>
        </div>
        <div className="hidden grid-cols-[24px_96px_88px_190px_1fr] gap-x-3 bg-hundido px-4 py-2 text-xs font-semibold text-texto-2 md:grid" aria-hidden="true">
          <span />
          <span>Fecha</span>
          <span>Turno</span>
          <span>Resultado</span>
          <span>Ciclos y mensajes</span>
        </div>
        {visibles.length === 0 ? (
          <p className="px-4 py-6 text-center text-[13px] text-texto-2">
            {filtro === "cambios" ? "Todo el archivo es igual a lo ya registrado: no hay nada que aplicar." : "No hay turno-días con este resultado."}
          </p>
        ) : (
          <ul aria-label="Turno-días de la carga">
            {visibles.map((g) => (
              <FilaGrupo key={g.id} g={g} bloqueada={bloqueada} onCambiar={onCambiar} />
            ))}
          </ul>
        )}
        {filtrados.length > POR_PAGINA && (
          <nav aria-label="Paginación del detalle" className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
            <p className="cifras text-xs text-texto-2">
              {((paginaActual - 1) * POR_PAGINA + 1).toLocaleString("es-PE")}–
              {Math.min(paginaActual * POR_PAGINA, filtrados.length).toLocaleString("es-PE")} de{" "}
              {filtrados.length.toLocaleString("es-PE")}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variante="secundario"
                tamano="sm"
                icono={<ChevronLeft aria-hidden="true" />}
                disabled={paginaActual <= 1}
                onClick={() => setPagina(paginaActual - 1)}
              >
                Anterior
              </Button>
              <Button
                variante="secundario"
                tamano="sm"
                className="flex-row-reverse"
                icono={<ChevronRight aria-hidden="true" />}
                disabled={paginaActual >= totalPaginas}
                onClick={() => setPagina(paginaActual + 1)}
              >
                Siguiente
              </Button>
            </div>
          </nav>
        )}
      </Card>
    </div>
  );
}
