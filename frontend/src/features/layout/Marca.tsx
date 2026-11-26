import { Droplet } from "lucide-react";

import { cn } from "../../lib/cn";

/** Isotipo + nombre del sistema (barra lateral y cajón del celular). */
export function Marca({ compacta }: { compacta?: boolean }) {
  return (
    <div className={cn("flex items-center gap-2.5", compacta ? "justify-center" : "px-2")}>
      <span
        className="relative flex size-9 shrink-0 items-center justify-center overflow-hidden rounded-[11px] bg-marca bg-[image:var(--degradado-marca)] text-white shadow-marca"
        aria-hidden="true"
      >
        <span className="absolute -top-3 -right-3 size-7 rounded-full bg-lima/40 blur-[6px]" />
        <Droplet className="relative size-[18px]" strokeWidth={2} />
      </span>
      <span className={cn("flex min-w-0 flex-col", compacta && "sr-only")}>
        <span className="text-[15px] leading-[18px] font-bold tracking-[-0.01em] text-green-900">
          <span className="text-green-600">i</span>TAL
        </span>
        <span className="text-[11px] leading-4 font-medium text-texto-3">Grupo El Rocío</span>
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
        "flex size-8 shrink-0 items-center justify-center rounded-full bg-marca bg-[image:var(--degradado-marca)] text-xs font-bold text-white ring-2 ring-white shadow-marca",
        className,
      )}
      aria-hidden="true"
    >
      {iniciales(nombre)}
    </span>
  );
}
