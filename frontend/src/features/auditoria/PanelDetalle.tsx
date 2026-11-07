import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "../../components/ui/Badge";
import { DialogContent } from "../../components/ui/Dialog";
import { cn } from "../../lib/cn";
import { formatearFechaHora } from "../../lib/fechas";
import type { RegistroAuditoria } from "./api";
import {
  analizarDetalle,
  etiquetaAccion,
  etiquetaCampo,
  etiquetaEntidad,
  etiquetaRol,
  formatearValor,
  tonoAccion,
} from "./etiquetas";

function Dato({ etiqueta, children, ancho }: { etiqueta: string; children: ReactNode; ancho?: boolean }) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-0.5", ancho && "col-span-2")}>
      <dt className="text-xs text-texto-2">{etiqueta}</dt>
      <dd className="m-0 text-[13px] break-words text-texto">{children}</dd>
    </div>
  );
}

/** Panel lateral con el registro completo y los cambios antes → después. */
export function PanelDetalle({ registro }: { registro: RegistroAuditoria }) {
  const { cambios, otros } = analizarDetalle(registro.detalle);
  return (
    <DialogContent
      lado="derecha"
      titulo={etiquetaAccion(registro.accion)}
      descripcion={`${formatearFechaHora(registro.ocurrido_at)} (hora de Lima)`}
    >
      <div className="flex flex-col gap-5">
        <div>
          <Badge tono={tonoAccion(registro.accion)}>{registro.accion}</Badge>
        </div>
        <dl className="cifras grid grid-cols-2 gap-x-4 gap-y-3">
          <Dato etiqueta="Usuario">{registro.username ?? "Sistema"}</Dato>
          <Dato etiqueta="Rol">{etiquetaRol(registro.rol)}</Dato>
          <Dato etiqueta="Entidad">{registro.entidad ? etiquetaEntidad(registro.entidad) : "—"}</Dato>
          <Dato etiqueta="ID de la entidad">{registro.entidad_id ?? "—"}</Dato>
          <Dato etiqueta="IP">
            <span className="font-mono text-xs">{registro.ip ?? "—"}</span>
          </Dato>
          <Dato etiqueta="Registro">#{registro.id}</Dato>
          <Dato etiqueta="Navegador" ancho>
            <span className="text-xs text-texto-2">{registro.user_agent ?? "—"}</span>
          </Dato>
        </dl>

        {cambios.length > 0 && (
          <section className="flex flex-col gap-2" aria-labelledby="titulo-cambios">
            <h3 id="titulo-cambios" className="text-sm font-semibold">
              Cambios
            </h3>
            <div className="relative overflow-x-auto rounded-lg border border-borde">
              <table className="cifras w-full border-collapse text-[13px]">
                <thead>
                  <tr>
                    <th scope="col" className="border-b border-borde bg-hundido px-3 py-2 text-left text-xs font-semibold text-texto-2">
                      Campo
                    </th>
                    <th scope="col" className="border-b border-borde bg-hundido px-3 py-2 text-left text-xs font-semibold text-texto-2">
                      Antes
                    </th>
                    <th scope="col" className="border-b border-borde bg-hundido px-3 py-2 text-left text-xs font-semibold text-texto-2">
                      <span className="sr-only">cambia a </span>Después
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {cambios.map((c) => (
                    <tr key={c.campo} className="align-top">
                      <th scope="row" className="border-b border-borde px-3 py-2 text-left font-medium text-texto">
                        {etiquetaCampo(c.campo)}
                      </th>
                      <td className={cn("border-b border-borde px-3 py-2 break-words", c.cambio ? "text-texto-3 line-through" : "text-texto-2")}>
                        {formatearValor(c.antes, c.campo)}
                      </td>
                      <td className="border-b border-borde px-3 py-2 break-words">
                        {c.cambio ? (
                          <span className="inline-flex items-center gap-1 rounded bg-warn-bg px-1.5 py-0.5 font-semibold text-warn-tx">
                            <ArrowRight className="size-3 shrink-0" aria-hidden="true" />
                            {formatearValor(c.despues, c.campo)}
                          </span>
                        ) : (
                          <span className="text-texto-2">{formatearValor(c.despues, c.campo)}</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {otros.length > 0 && (
          <section className="flex flex-col gap-2" aria-labelledby="titulo-otros">
            <h3 id="titulo-otros" className="text-sm font-semibold">
              {cambios.length > 0 ? "Otros datos" : "Detalle"}
            </h3>
            <dl className="grid grid-cols-1 gap-2 rounded-lg border border-borde bg-fondo p-3 sm:grid-cols-2">
              {otros.map(([clave, valor]) => (
                <Dato key={clave} etiqueta={etiquetaCampo(clave)}>
                  {formatearValor(valor, clave)}
                </Dato>
              ))}
            </dl>
          </section>
        )}

        {cambios.length === 0 && otros.length === 0 && <p className="text-[13px] text-texto-2">Sin detalle adicional.</p>}
      </div>
    </DialogContent>
  );
}
