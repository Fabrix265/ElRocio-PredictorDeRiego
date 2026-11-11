import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type { ReactElement, ReactNode } from "react";

export const TooltipProvider = TooltipPrimitive.Provider;

/** Tooltip simple. Si `desactivado`, devuelve el hijo sin envolver. */
export function Tooltip({
  texto,
  children,
  lado = "right",
  desactivado,
}: {
  texto: ReactNode;
  children: ReactElement;
  lado?: "top" | "right" | "bottom" | "left";
  desactivado?: boolean;
}) {
  if (desactivado) return children;
  return (
    <TooltipPrimitive.Root>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={lado}
          sideOffset={8}
          className="z-50 rounded-md bg-green-900 px-2.5 py-1.5 text-xs font-medium text-white shadow-elevada"
        >
          {texto}
          <TooltipPrimitive.Arrow className="fill-green-900" />
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
