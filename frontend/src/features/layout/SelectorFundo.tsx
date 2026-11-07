import { AlertTriangle, ChevronRight } from "lucide-react";
import { useRef, type KeyboardEvent } from "react";

import { Skeleton } from "../../components/ui/Skeleton";
import { cn } from "../../lib/cn";
import { useSeleccion } from "../catalogo/SeleccionProvider";

interface OpcionSegmento {
  valor: string;
  etiqueta: string;
  titulo?: string;
}

/** Grupo de píldoras con semántica de radio y flechas del teclado (tabindex itinerante). */
function Segmento({
  etiqueta,
  opciones,
  valor,
  alCambiar,
}: {
  etiqueta: string;
  opciones: OpcionSegmento[];
  valor: string | undefined;
  alCambiar: (valor: string) => void;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const indiceActual = Math.max(0, opciones.findIndex((o) => o.valor === valor));

  const alTeclear = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const delta = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!delta) return;
    e.preventDefault();
    const siguiente = (i + delta + opciones.length) % opciones.length;
    alCambiar(opciones[siguiente].valor);
    refs.current[siguiente]?.focus();
  };

  return (
    <div
      role="radiogroup"
      aria-label={etiqueta}
      className="flex shrink-0 items-center gap-1 rounded-full border border-borde bg-hundido p-1"
    >
      {opciones.map((op, i) => {
        const activo = i === indiceActual;
        return (
          <button
            key={op.valor}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={activo}
            tabIndex={activo ? 0 : -1}
            title={op.titulo}
            onClick={() => alCambiar(op.valor)}
            onKeyDown={(e) => alTeclear(e, i)}
            className={cn(
              "h-7 rounded-full px-3 text-[13px] whitespace-nowrap transition-colors",
              "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-foco",
              activo ? "bg-superficie font-semibold text-texto shadow-suave" : "text-texto-2 hover:text-activo-tx",
            )}
          >
            {op.etiqueta}
          </button>
        );
      })}
    </div>
  );
}

/** Selector Fundo › Módulo de la cabecera; se desliza horizontalmente si no cabe. */
export function SelectorFundo() {
  const { fundos, fundo, modulo, cargando, error, seleccionarFundo, seleccionarModulo } = useSeleccion();

  if (cargando) {
    return (
      <div className="flex items-center gap-2" aria-busy="true" aria-label="Cargando fundos">
        <Skeleton className="h-9 w-28 rounded-full" />
        <Skeleton className="h-9 w-28 rounded-full" />
      </div>
    );
  }

  if (error || !fundo) {
    return (
      <span className="inline-flex items-center gap-1.5 text-[13px] text-texto-2">
        <AlertTriangle className="size-4 text-warn" aria-hidden="true" />
        {error ? "No se pudo cargar el catálogo de fundos" : "Sin fundos registrados"}
      </span>
    );
  }

  return (
    <nav aria-label="Fundo y módulo" className="sin-barra -my-1 flex min-w-0 items-center gap-1.5 overflow-x-auto py-1">
      <Segmento
        etiqueta="Fundo"
        valor={fundo.codigo}
        alCambiar={seleccionarFundo}
        opciones={fundos.map((f) => ({ valor: f.codigo, etiqueta: f.nombre, titulo: f.codigo }))}
      />
      {fundo.modulos.length > 0 && (
        <>
          <ChevronRight className="size-4 shrink-0 text-texto-3" aria-hidden="true" />
          <Segmento
            etiqueta="Módulo"
            valor={modulo?.codigo}
            alCambiar={seleccionarModulo}
            opciones={fundo.modulos.map((m) => ({ valor: m.codigo, etiqueta: m.codigo, titulo: m.nombre }))}
          />
        </>
      )}
    </nav>
  );
}
