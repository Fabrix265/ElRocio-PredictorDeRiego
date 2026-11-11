import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

type Lado = "centro" | "derecha" | "izquierda";

interface DialogContentProps {
  titulo: ReactNode;
  descripcion?: ReactNode;
  children?: ReactNode;
  /** Botones al pie (alineados a la derecha; en celular se apilan). */
  pie?: ReactNode;
  /** "centro" = diálogo modal; "derecha"/"izquierda" = panel lateral (cajón). */
  lado?: Lado;
  ancho?: "sm" | "md" | "lg";
  className?: string;
  /** Oculta el título visualmente (sigue disponible para lectores de pantalla). */
  ocultarTitulo?: boolean;
}

const ANCHOS = { sm: "sm:max-w-sm", md: "sm:max-w-lg", lg: "sm:max-w-2xl" };

export function DialogContent({
  titulo,
  descripcion,
  children,
  pie,
  lado = "centro",
  ancho = "md",
  className,
  ocultarTitulo,
}: DialogContentProps) {
  const esPanel = lado !== "centro";
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-green-900/40 data-[state=open]:animate-[aparecer_150ms_ease-out]" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 flex flex-col bg-superficie shadow-elevada focus:outline-none",
          esPanel
            ? cn(
                "inset-y-0 w-[min(100vw,440px)] max-w-full",
                lado === "derecha" ? "right-0 border-l border-borde" : "left-0 border-r border-borde",
              )
            : cn(
                "inset-x-4 top-1/2 max-h-[calc(100dvh-32px)] -translate-y-1/2 rounded-xl border border-borde",
                "sm:inset-x-auto sm:left-1/2 sm:w-full sm:-translate-x-1/2",
                ANCHOS[ancho],
              ),
          className,
        )}
        {...(descripcion ? {} : { "aria-describedby": undefined })}
      >
        <div className="flex items-start justify-between gap-3 border-b border-borde px-5 py-4">
          <div className={cn("flex min-w-0 flex-col gap-1", ocultarTitulo && "sr-only")}>
            <DialogPrimitive.Title className="text-base leading-6 font-semibold text-texto">{titulo}</DialogPrimitive.Title>
            {descripcion && (
              <DialogPrimitive.Description className="text-[13px] text-texto-2">{descripcion}</DialogPrimitive.Description>
            )}
          </div>
          <DialogPrimitive.Close
            className="-mr-1 inline-flex size-8 shrink-0 items-center justify-center rounded-md text-texto-2 hover:bg-activo-bg hover:text-activo-tx focus-visible:outline-2 focus-visible:outline-foco"
            aria-label="Cerrar"
          >
            <X className="size-4" aria-hidden="true" />
          </DialogPrimitive.Close>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
        {pie && (
          <div className="flex flex-col-reverse gap-2 border-t border-borde px-5 py-3 sm:flex-row sm:justify-end">{pie}</div>
        )}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
