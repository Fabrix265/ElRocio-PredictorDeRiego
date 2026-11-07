import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "../../lib/cn";

type TonoAlerta = "exito" | "aviso" | "error" | "info";

const ESTILOS: Record<TonoAlerta, { caja: string; icono: ReactNode }> = {
  exito: { caja: "bg-ok-bg text-ok-tx border-ok/25", icono: <CheckCircle2 aria-hidden="true" /> },
  aviso: { caja: "bg-warn-bg text-warn-tx border-warn/30", icono: <AlertTriangle aria-hidden="true" /> },
  error: { caja: "bg-err-bg text-err-tx border-err/25", icono: <XCircle aria-hidden="true" /> },
  info: { caja: "bg-info-bg text-info-tx border-info/25", icono: <Info aria-hidden="true" /> },
};

/** Mensaje en línea (errores de formulario, confirmaciones). Los errores se anuncian. */
export function Alert({
  tono = "info",
  titulo,
  children,
  className,
}: {
  tono?: TonoAlerta;
  titulo?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const { caja, icono } = ESTILOS[tono];
  return (
    <div
      role={tono === "error" ? "alert" : "status"}
      className={cn(
        "flex gap-2.5 rounded-md border px-3 py-2.5 text-[13px] leading-5 [&>svg]:mt-0.5 [&>svg]:size-4 [&>svg]:shrink-0",
        caja,
        className,
      )}
    >
      {icono}
      <div className="flex min-w-0 flex-col gap-0.5">
        {titulo && <p className="font-semibold">{titulo}</p>}
        {children && <div>{children}</div>}
      </div>
    </div>
  );
}
