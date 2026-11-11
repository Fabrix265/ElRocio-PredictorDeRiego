import { useQuery } from "@tanstack/react-query";
import { History, Moon } from "lucide-react";

import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { DialogContent } from "../../components/ui/Dialog";
import { Skeleton } from "../../components/ui/Skeleton";
import { Button } from "../../components/ui/Button";
import { puede } from "../../lib/roles";
import { useUsuario } from "../auth/AuthProvider";
import { AccionesRiego } from "./EditorRiego";
import { cn } from "../../lib/cn";
import { formatearDia, formatearFechaHora } from "../../lib/fechas";
import { mensajeDeError } from "../../services/httpClient";
import { claveRiego, riegoApi, type CicloRiego, type RegistroRiego, type VersionRiego } from "../../services/riego";
import type { Turno } from "../catalogo/api";
import {
  ETIQUETA_ESTADO_CELDA,
  TONO_ESTADO_CELDA,
  estadoCelda,
  etiquetaOrigen,
  formatearDuracion,
  formatearM3,
  formatearM3ha,
  resumirCiclos,
} from "./etiquetas";

const TH = "border-b border-borde bg-hundido px-2.5 py-2 text-left text-xs font-semibold text-texto-2";
const TD = "border-b border-borde px-2.5 py-2 whitespace-nowrap";

export function TablaCiclos({ ciclos, titulo }: { ciclos: CicloRiego[]; titulo: string }) {
  const r = resumirCiclos(ciclos);
  return (
    <div className="overflow-x-auto rounded-lg border border-borde">
      <table className="cifras w-full border-collapse text-[13px]">
        <caption className="sr-only">{titulo}</caption>
        <thead>
          <tr>
            <th scope="col" className={TH}>Ciclo</th>
            <th scope="col" className={TH}>Horario</th>
            <th scope="col" className={cn(TH, "text-right")}>Duración</th>
            <th scope="col" className={cn(TH, "text-right")}>m³/ha</th>
            <th scope="col" className={cn(TH, "text-right")}>m³</th>
          </tr>
        </thead>
        <tbody>
          {ciclos.map((c, i) => (
            <tr key={c.inicio_min}>
              <td className={TD}>{i + 1}</td>
              <td className={TD}>
                <span className="inline-flex items-center gap-1">
                  {c.hora_inicio}–{c.hora_fin}
                  {c.fin_dia_siguiente && (
                    <span className="inline-flex items-center gap-0.5 text-[11px] text-texto-3">
                      <Moon className="size-3" aria-hidden="true" />
                      +1 día
                    </span>
                  )}
                </span>
              </td>
              <td className={cn(TD, "text-right")}>{formatearDuracion(c.duracion_min)}</td>
              <td className={cn(TD, "text-right")}>{formatearM3ha(c.riego_m3ha)}</td>
              <td className={cn(TD, "text-right")}>{formatearM3(c.riego_m3)}</td>
            </tr>
          ))}
        </tbody>
        {ciclos.length > 1 && (
          <tfoot>
            <tr className="font-semibold">
              <th scope="row" colSpan={2} className="px-2.5 py-2 text-left text-xs">
                Total
              </th>
              <td className="px-2.5 py-2 text-right">{formatearDuracion(r.duracionMin)}</td>
              <td className="px-2.5 py-2 text-right">{formatearM3ha(r.m3ha)}</td>
              <td className="px-2.5 py-2 text-right">{formatearM3(r.m3)}</td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

function Version({ v }: { v: VersionRiego }) {
  const estado = estadoCelda(v);
  const r = resumirCiclos(v.ciclos);
  return (
    <li
      className={cn(
        "flex flex-col gap-1.5 rounded-lg border px-3 py-2.5",
        v.vigente ? "border-green-300 bg-activo-bg" : "border-borde bg-superficie",
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[13px] font-semibold text-texto">Versión {v.version}</span>
        {v.version === 1 && <Badge tono="neutro" icono={false}>Original</Badge>}
        {v.vigente && <Badge tono="marca">Vigente</Badge>}
        <Badge tono={TONO_ESTADO_CELDA[estado]}>{ETIQUETA_ESTADO_CELDA[estado]}</Badge>
      </div>
      <p className="text-xs text-texto-2">
        {etiquetaOrigen(v.origen)}
        {v.creado_at && <> · {formatearFechaHora(v.creado_at)}</>}
        {v.creado_por && <> · {v.creado_por}</>}
        {v.carga_id != null && <> · carga #{v.carga_id}</>}
      </p>
      <p className="cifras text-xs text-texto">
        {r.n === 0
          ? "Sin ciclos (no se regó)"
          : `${r.n} ${r.n === 1 ? "ciclo" : "ciclos"} · ${formatearM3ha(r.m3ha)} m³/ha · ${r.desde}–${r.hasta}${r.finDiaSiguiente ? " (+1 día)" : ""}`}
      </p>
      {(v.motivo || v.comentario) && (
        <p className="text-xs text-texto-2">
          {v.motivo && <span className="font-medium text-texto">{v.motivo}</span>}
          {v.motivo && v.comentario && " · "}
          {v.comentario}
        </p>
      )}
    </li>
  );
}

function HistorialVersiones({ turnoId, fecha }: { turnoId: number; fecha: string }) {
  const consulta = useQuery({
    queryKey: claveRiego.versiones(turnoId, fecha),
    queryFn: ({ signal }) => riegoApi.versiones(turnoId, fecha, signal),
  });
  return (
    <section className="flex flex-col gap-2" aria-labelledby="titulo-versiones" aria-busy={consulta.isPending || undefined}>
      <h3 id="titulo-versiones" className="flex items-center gap-1.5 text-sm font-semibold">
        <History className="size-4 text-green-600" aria-hidden="true" />
        Historial de versiones
      </h3>
      {consulta.isPending ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      ) : consulta.isError ? (
        <Alert tono="error" titulo="No se pudo cargar el historial">
          {mensajeDeError(consulta.error)}{" "}
          <button type="button" className="font-semibold underline" onClick={() => void consulta.refetch()}>
            Reintentar
          </button>
        </Alert>
      ) : consulta.data.length === 0 ? (
        <p className="text-[13px] text-texto-2">Sin versiones registradas.</p>
      ) : (
        <ol className="flex flex-col gap-2">
          {consulta.data.map((v) => (
            <Version key={v.id} v={v} />
          ))}
        </ol>
      )}
    </section>
  );
}

/** Panel lateral: riego vigente de un turno-día y (A, E, S) su historial de versiones. */
export function PanelTurnoDia({
  turno,
  fecha,
  registro: recibido,
  verVersiones,
}: {
  turno: Turno;
  fecha: string;
  registro: RegistroRiego | null;
  verVersiones: boolean;
}) {
  const usuario = useUsuario();
  const puedeEditar = puede(usuario.rol, "editarRiego");
  // La selección de la página contiene una foto; obtener el vigente evita seguir mostrando
  // esa foto después de guardar o de resolver un conflicto.
  const actual = useQuery({
    queryKey: claveRiego.versiones(turno.id, fecha),
    queryFn: ({ signal }) => riegoApi.versiones(turno.id, fecha, signal),
    enabled: puedeEditar,
  });
  const registro = actual.data?.find((v) => v.vigente) ?? recibido;
  const estado = estadoCelda(registro ?? undefined);
  return (
    <DialogContent
      lado="derecha"
      titulo={`${turno.codigo} · ${formatearDia(fecha)}`}
      descripcion={registro ? `Riego ${ETIQUETA_ESTADO_CELDA[estado].toLowerCase()} · versión ${registro.version}` : "Sin registro de riego"}
    >
      <div className="flex flex-col gap-5">
        {registro ? (
        <section className="flex flex-col gap-2" aria-labelledby="titulo-vigente">
          <h3 id="titulo-vigente" className="text-sm font-semibold">
            Riego vigente
          </h3>
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tono={TONO_ESTADO_CELDA[estado]}>{ETIQUETA_ESTADO_CELDA[estado]}</Badge>
            <Badge tono="neutro" icono={false}>
              Origen: {etiquetaOrigen(registro.origen)}
            </Badge>
          </div>
          {(registro.creado_at || registro.creado_por) && (
            <p className="text-xs text-texto-2">
              Registrado {registro.creado_at && <>el {formatearFechaHora(registro.creado_at)}</>}
              {registro.creado_por && <> por {registro.creado_por}</>}
            </p>
          )}
          {registro.sin_riego ? (
            <Alert tono="info" titulo="No se regó">
              {[registro.motivo, registro.comentario].filter(Boolean).join(" · ") || "El turno quedó registrado sin riego ese día."}
            </Alert>
          ) : (
            <TablaCiclos ciclos={registro.ciclos} titulo={`Ciclos de ${turno.codigo} el ${formatearDia(fecha)}`} />
          )}
        </section>
        ) : (
          <p className="text-[13px] text-texto-2">
            Este turno-día no tiene riego registrado. Puedes cargarlo con «Editar riego» o indicar que no se regó.
          </p>
        )}
        {puedeEditar && actual.isError && <Alert tono="error">{mensajeDeError(actual.error)} <Button variante="fantasma" disabled={actual.isFetching} onClick={() => void actual.refetch()}>Recargar</Button></Alert>}
        {puedeEditar && (actual.isPending ? (
          <Skeleton className="h-16" />
        ) : actual.data ? (
          <AccionesRiego key={`${turno.id}-${fecha}`} registro={registro} turnoId={turno.id} fecha={fecha} alRecargar={() => actual.refetch()} />
        ) : null)}
        {verVersiones && <HistorialVersiones turnoId={turno.id} fecha={fecha} />}
      </div>
    </DialogContent>
  );
}
