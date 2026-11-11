import { Skeleton } from "../components/ui/Skeleton";

/** Esqueleto de una sección mientras se descarga su código. */
export function CargandoSeccion() {
  return (
    <div className="flex flex-col gap-4" role="status" aria-live="polite">
      <span className="sr-only">Cargando…</span>
      <Skeleton className="h-3 w-24" />
      <Skeleton className="h-7 w-64" />
      <Skeleton className="h-12 w-full" />
      <Skeleton className="h-80 w-full" />
    </div>
  );
}
