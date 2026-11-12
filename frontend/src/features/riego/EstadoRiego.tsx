import { Ban, Minus } from "lucide-react";
import { Badge } from "../../components/ui/Badge";
import { ETIQUETA_ESTADO_CELDA, TONO_ESTADO_CELDA, type EstadoCelda } from "./etiquetas";

export function EstadoRiego({ estado }: { estado: EstadoCelda }) {
  return <Badge ajustar tono={TONO_ESTADO_CELDA[estado]}
    icono={estado === "sin_riego" ? <Ban aria-hidden="true" /> : estado === "sin_registro" ? <Minus aria-hidden="true" /> : undefined}
    className={estado === "sin_registro" ? "border-dashed bg-transparent! text-texto-3!" : undefined}>
    {ETIQUETA_ESTADO_CELDA[estado]}
  </Badge>;
}
