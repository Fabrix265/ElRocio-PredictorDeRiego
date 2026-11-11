import { Droplet } from "lucide-react";

import { cn } from "../../lib/cn";

/** Isotipo + nombre del sistema (barra lateral y cajón del celular). */
export function Marca({ compacta }: { compacta?: boolean }) {
  return (
    <div className={cn("flex items-center gap-2.5", compacta ? "justify-center" : "px-2")}>
      <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-marca text-white" aria-hidden="true">
        <Droplet className="size-[18px]" strokeWidth={1.9} />
      </span>
      <span className={cn("flex min-w-0 flex-col", compacta && "sr-only")}>
        <span className="text-sm leading-[18px] font-semibold text-green-800">Plan de Riego</span>
        <span className="text-[11px] leading-4 text-texto-3">Grupo El Rocío</span>
      </span>
    </div>
  );
}

export function iniciales(nombre: string): string {
  const partes = nombre.trim().split(/\s+/).filter(Boolean);
  const letras = partes.length > 1 ? partes[0][0] + partes[partes.length - 1][0] : (partes[0] ?? "?").slice(0, 2);
  return letras.toUpperCase();
}

export function Avatar({ nombre, className }: { nombre: string; className?: string }) {
  return (
    <span
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-full bg-marca text-xs font-bold text-white",
        className,
      )}
      aria-hidden="true"
    >
      {iniciales(nombre)}
    </span>
  );
}
