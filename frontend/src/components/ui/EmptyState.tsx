import { Sprout } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

interface EmptyStateProps {
  titulo: ReactNode;
  descripcion?: ReactNode;
  icono?: ReactNode;
  accion?: ReactNode;
  compacto?: boolean;
  className?: string;
}

export function EmptyState({ titulo, descripcion, icono, accion, compacto, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 text-center",
        compacto ? "px-4 py-6" : "px-6 py-12",
        className,
      )}
    >
      <span
        className={cn(
          "flex items-center justify-center rounded-full bg-green-50 text-green-600 [&_svg]:shrink-0",
          compacto ? "size-10 [&_svg]:size-5" : "size-14 [&_svg]:size-7",
        )}
        aria-hidden="true"
      >
        {icono ?? <Sprout />}
      </span>
      <div className="flex max-w-md flex-col gap-1">
        <p className={cn("font-semibold text-texto", compacto ? "text-sm" : "text-base")}>{titulo}</p>
        {descripcion && <p className="text-[13px] text-texto-2">{descripcion}</p>}
      </div>
      {accion}
    </div>
  );
}
