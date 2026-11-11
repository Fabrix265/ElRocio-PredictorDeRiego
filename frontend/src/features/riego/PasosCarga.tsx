import { Check } from "lucide-react";

import { cn } from "../../lib/cn";

const PASOS = ["Subir archivo", "Revisar vista previa", "Confirmado"] as const;

/** Indicador del asistente de carga (1 subir · 2 revisar · 3 confirmado). */
export function PasosCarga({ actual }: { actual: 1 | 2 | 3 }) {
  return (
    <ol className="flex flex-wrap items-center gap-x-3 gap-y-2" aria-label="Pasos de la carga">
      {PASOS.map((nombre, i) => {
        const n = i + 1;
        const hecho = n < actual || (n === 3 && actual === 3);
        const activo = n === actual;
        return (
          <li key={nombre} className="flex items-center gap-2" aria-current={activo ? "step" : undefined}>
            <span
              className={cn(
                "flex size-6 items-center justify-center rounded-full border text-xs font-semibold",
                hecho ? "border-marca bg-marca text-white" : activo ? "border-marca text-marca" : "border-borde text-texto-3",
              )}
              aria-hidden="true"
            >
              {hecho ? <Check className="size-3.5" /> : n}
            </span>
            <span className={cn("text-[13px]", activo ? "font-semibold text-texto" : "text-texto-2")}>{nombre}</span>
            {n < PASOS.length && <span className="hidden h-px w-6 bg-borde sm:block" aria-hidden="true" />}
          </li>
        );
      })}
    </ol>
  );
}
