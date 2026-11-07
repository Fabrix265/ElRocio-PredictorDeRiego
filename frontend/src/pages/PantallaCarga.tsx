import { Skeleton } from "../components/ui/Skeleton";

/** Esqueleto de la app mientras se verifica la sesión al cargar. */
export function PantallaCarga() {
  return (
    <div className="flex min-h-dvh" role="status" aria-live="polite">
      <span className="sr-only">Cargando…</span>
      <div className="hidden w-[var(--sidebar-ancho)] shrink-0 flex-col gap-2 border-r border-borde bg-sidebar p-4 md:flex">
        <div className="mb-4 flex items-center gap-2.5">
          <Skeleton className="size-8 rounded-md" />
          <div className="flex flex-col gap-1.5">
            <Skeleton className="h-3.5 w-24" />
            <Skeleton className="h-2.5 w-16" />
          </div>
        </div>
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-9 w-full" />
        ))}
      </div>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-[var(--cabecera-alto)] items-center gap-3 border-b-[3px] border-marca bg-superficie px-5">
          <Skeleton className="h-8 w-28 rounded-full" />
          <Skeleton className="h-8 w-28 rounded-full" />
        </div>
        <div className="flex flex-col gap-4 p-5">
          <Skeleton className="h-7 w-56" />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
          <Skeleton className="h-64" />
        </div>
      </div>
    </div>
  );
}
