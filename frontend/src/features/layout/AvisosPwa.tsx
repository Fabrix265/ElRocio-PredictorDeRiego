import { Download, RefreshCw, WifiOff, X } from "lucide-react";

import { cn } from "../../lib/cn";
import { actualizarApp, descartarActualizacion, instalarApp, usePwa } from "../../lib/pwa";

/** Franja superior cuando no hay conexión: los datos pueden no estar al día. */
export function AvisoSinConexion() {
  const { enLinea } = usePwa();
  if (enLinea) return null;
  return (
    <div role="status" className="flex items-center justify-center gap-2 bg-warn-bg px-4 py-1.5 text-center text-xs font-medium text-warn-tx">
      <WifiOff className="size-3.5 shrink-0" aria-hidden="true" />
      Sin conexión: lo que ves puede no estar al día y no se podrán guardar cambios hasta que vuelva la señal.
    </div>
  );
}

/** Tarjeta flotante cuando hay una versión nueva de la app lista para usar. */
export function AvisoActualizacion() {
  const { hayActualizacion } = usePwa();
  if (!hayActualizacion) return null;
  return (
    <div
      role="status"
      className="entrada-suave fixed right-4 bottom-[calc(76px+env(safe-area-inset-bottom))] left-4 z-40 flex items-center gap-3 rounded-lg border border-borde bg-superficie p-3 shadow-elevada sm:left-auto sm:w-[360px] md:bottom-5"
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-green-50 text-green-600" aria-hidden="true">
        <RefreshCw className="size-4" />
      </span>
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="text-[13px] font-semibold text-texto">Hay una versión nueva</span>
        <span className="text-xs text-texto-2">Actualiza cuando termines lo que estás haciendo.</span>
      </div>
      <button
        type="button"
        onClick={actualizarApp}
        className="h-8 shrink-0 rounded-md bg-marca px-3 text-[13px] font-semibold text-white hover:bg-marca-hover focus-visible:outline-2 focus-visible:outline-foco"
      >
        Actualizar
      </button>
      <button
        type="button"
        onClick={descartarActualizacion}
        aria-label="Más tarde"
        className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-texto-3 hover:bg-hundido focus-visible:outline-2 focus-visible:outline-foco"
      >
        <X className="size-4" aria-hidden="true" />
      </button>
    </div>
  );
}

/** Botón «Instalar app»: solo aparece cuando el navegador permite instalarla. */
export function BotonInstalar({ compacto, className, alInstalar }: { compacto?: boolean; className?: string; alInstalar?: () => void }) {
  const { instalable } = usePwa();
  if (!instalable) return null;
  return (
    <button
      type="button"
      onClick={() => {
        alInstalar?.();
        void instalarApp();
      }}
      aria-label={compacto ? "Instalar la app" : undefined}
      title={compacto ? "Instalar la app" : undefined}
      className={cn(
        "flex h-10 w-full items-center gap-2.5 rounded-md border border-green-200 bg-green-50 text-[13px] font-semibold text-green-700",
        "transition-colors hover:border-green-300 hover:bg-green-100 focus-visible:outline-2 focus-visible:outline-foco",
        compacto ? "justify-center" : "px-2.5",
        className,
      )}
    >
      <Download className="size-[18px] shrink-0" strokeWidth={1.9} aria-hidden="true" />
      {!compacto && <span className="flex flex-col items-start leading-tight">Instalar la app<span className="text-[11px] font-normal text-green-600">Acceso directo y pantalla completa</span></span>}
    </button>
  );
}
