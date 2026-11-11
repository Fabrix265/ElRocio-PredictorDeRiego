import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useState, type ReactNode } from "react";

import { cn } from "../../lib/cn";
import { Skeleton } from "./Skeleton";

export interface MetaColumna {
  /** Alinea a la derecha (cifras). */
  numerica?: boolean;
  /** Clases extra de la celda (p. ej. ancho). */
  className?: string;
}

interface DataTableProps<T> {
  columnas: ColumnDef<T, unknown>[];
  datos: T[] | undefined;
  cargando?: boolean;
  /** Contenido cuando no hay filas (normalmente un EmptyState). */
  vacio?: ReactNode;
  getRowId?: (fila: T) => string;
  onFilaClick?: (fila: T) => void;
  /** Etiqueta accesible de la acción de fila (p. ej. "Ver detalle"). */
  etiquetaFila?: (fila: T) => string;
  filaSeleccionadaId?: string | null;
  ordenInicial?: SortingState;
  /** Desactiva el ordenamiento en el cliente (p. ej. tablas paginadas en el servidor). */
  sinOrden?: boolean;
  filasSkeleton?: number;
  titulo: string;
}

export function DataTable<T>({
  columnas,
  datos,
  cargando,
  vacio,
  getRowId,
  onFilaClick,
  etiquetaFila,
  filaSeleccionadaId,
  ordenInicial = [],
  sinOrden,
  filasSkeleton = 6,
  titulo,
}: DataTableProps<T>) {
  const [orden, setOrden] = useState<SortingState>(ordenInicial);
  const tabla = useReactTable({
    data: datos ?? [],
    columns: columnas,
    state: { sorting: orden },
    onSortingChange: setOrden,
    enableSorting: !sinOrden,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getRowId,
  });

  const filas = tabla.getRowModel().rows;
  const nColumnas = tabla.getVisibleLeafColumns().length;

  return (
    <div className="relative w-full overflow-x-auto" aria-busy={cargando || undefined}>
      <table className="cifras w-full border-collapse text-[13px]">
        <caption className="sr-only">{titulo}</caption>
        <thead>
          {tabla.getHeaderGroups().map((grupo) => (
            <tr key={grupo.id}>
              {grupo.headers.map((cabecera) => {
                const meta = cabecera.column.columnDef.meta as MetaColumna | undefined;
                const ordenable = cabecera.column.getCanSort();
                const sentido = cabecera.column.getIsSorted();
                const contenido = flexRender(cabecera.column.columnDef.header, cabecera.getContext());
                return (
                  <th
                    key={cabecera.id}
                    scope="col"
                    aria-sort={sentido === "asc" ? "ascending" : sentido === "desc" ? "descending" : undefined}
                    className={cn(
                      "border-b border-borde bg-hundido px-3 py-2.5 text-left text-xs font-semibold whitespace-nowrap text-texto-2",
                      meta?.numerica && "text-right",
                      meta?.className,
                    )}
                  >
                    {cabecera.isPlaceholder ? null : ordenable ? (
                      <button
                        type="button"
                        onClick={cabecera.column.getToggleSortingHandler()}
                        className={cn(
                          "-mx-1 inline-flex items-center gap-1 rounded px-1 hover:text-texto focus-visible:outline-2 focus-visible:outline-foco",
                          meta?.numerica && "flex-row-reverse",
                        )}
                      >
                        {contenido}
                        {sentido === "asc" ? (
                          <ArrowUp className="size-3.5" aria-hidden="true" />
                        ) : sentido === "desc" ? (
                          <ArrowDown className="size-3.5" aria-hidden="true" />
                        ) : (
                          <ChevronsUpDown className="size-3.5 opacity-50" aria-hidden="true" />
                        )}
                      </button>
                    ) : (
                      contenido
                    )}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {cargando && !datos?.length ? (
            Array.from({ length: filasSkeleton }, (_, i) => (
              <tr key={`sk-${i}`}>
                {Array.from({ length: nColumnas }, (_, j) => (
                  <td key={j} className="border-b border-borde px-3 py-3">
                    <Skeleton className={cn("h-4", j === 0 ? "w-36" : "w-20")} />
                  </td>
                ))}
              </tr>
            ))
          ) : filas.length === 0 ? (
            <tr>
              <td colSpan={nColumnas} className="border-b border-borde">
                {vacio}
              </td>
            </tr>
          ) : (
            filas.map((fila) => {
              const seleccionada = filaSeleccionadaId != null && fila.id === filaSeleccionadaId;
              return (
                <tr
                  key={fila.id}
                  onClick={onFilaClick ? () => onFilaClick(fila.original) : undefined}
                  onKeyDown={
                    onFilaClick
                      ? (e) => {
                          if (e.target !== e.currentTarget) return;
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            onFilaClick(fila.original);
                          }
                        }
                      : undefined
                  }
                  tabIndex={onFilaClick ? 0 : undefined}
                  aria-label={onFilaClick && etiquetaFila ? etiquetaFila(fila.original) : undefined}
                  className={cn(
                    "transition-colors",
                    onFilaClick && "cursor-pointer hover:bg-activo-bg focus-visible:bg-activo-bg focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-foco",
                    seleccionada && "bg-activo-bg",
                  )}
                >
                  {fila.getVisibleCells().map((celda) => {
                    const meta = celda.column.columnDef.meta as MetaColumna | undefined;
                    return (
                      <td
                        key={celda.id}
                        className={cn(
                          "border-b border-borde px-3 py-2.5 align-middle whitespace-nowrap text-texto",
                          meta?.numerica && "text-right",
                          meta?.className,
                        )}
                      >
                        {flexRender(celda.column.columnDef.cell, celda.getContext())}
                      </td>
                    );
                  })}
                </tr>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
