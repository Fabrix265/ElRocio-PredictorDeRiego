import { AlertTriangle, CheckCircle2, CircleDot, Info, MinusCircle, XCircle } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

export type TonoBadge = "exito" | "aviso" | "error" | "info" | "neutro" | "marca";

const TONOS: Record<TonoBadge, string> = {
  exito: "bg-ok-bg text-ok-tx ring-1 ring-inset ring-ok/15",
  aviso: "bg-warn-bg text-warn-tx ring-1 ring-inset ring-warn/20",
  error: "bg-err-bg text-err-tx ring-1 ring-inset ring-err/15",
  info: "bg-info-bg text-info-tx ring-1 ring-inset ring-info/15",
  neutro: "bg-hundido text-texto-2 ring-1 ring-inset ring-borde",
  marca: "bg-green-50 text-green-700",
};

const ICONOS: Record<TonoBadge, ReactNode> = {
  exito: <CheckCircle2 aria-hidden="true" />,
  aviso: <AlertTriangle aria-hidden="true" />,
  error: <XCircle aria-hidden="true" />,
  info: <Info aria-hidden="true" />,
  neutro: <MinusCircle aria-hidden="true" />,
  marca: <CircleDot aria-hidden="true" />,
};

interface BadgeProps {
  tono?: TonoBadge;
  children: ReactNode;
  /** Ícono propio; `false` para omitirlo (solo si el texto basta). Por defecto, el del tono. */
  icono?: ReactNode | false;
  className?: string;
  /** Permite que el texto haga salto de línea en contenedores angostos (celular). */
  ajustar?: boolean;
}

/** Chip de estado: siempre ícono + texto (el color no es la única señal). */
export function Badge({ tono = "neutro", children, icono, className, ajustar = false }: BadgeProps) {
  const simbolo = icono === false ? null : (icono ?? ICONOS[tono]);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2.5 text-xs font-medium [&_svg]:size-3.5 [&_svg]:shrink-0",
        ajustar
          ? "min-h-[22px] max-w-full rounded-[11px] py-0.5 leading-4 whitespace-normal"
          : "h-[22px] rounded-full whitespace-nowrap",
        TONOS[tono],
        className,
      )}
    >
      {simbolo}
      {children}
    </span>
  );
}
