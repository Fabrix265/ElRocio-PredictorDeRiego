import { cn } from "../../lib/cn";

/** Bloque de carga (decorativo: los contenedores anuncian aria-busy). */
export function Skeleton({ className }: { className?: string }) {
  return <div
      aria-hidden="true"
      className={cn(
        "rounded-md bg-sand-100 bg-[linear-gradient(90deg,transparent_0%,rgb(255_255_255/0.7)_50%,transparent_100%)] bg-size-[200%_100%] animate-[brillo_1.6s_ease-in-out_infinite]",
        className,
      )}
    />;
}
