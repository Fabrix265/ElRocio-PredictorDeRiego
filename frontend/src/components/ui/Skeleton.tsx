import { cn } from "../../lib/cn";

/** Bloque de carga (decorativo: los contenedores anuncian aria-busy). */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("animate-pulse rounded-md bg-sand-100", className)} />;
}
