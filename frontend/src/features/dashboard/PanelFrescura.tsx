import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Info, Loader2, RefreshCcw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardBody, CardHeader } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { notificar } from "../../components/ui/Toast";
import { cn } from "../../lib/cn";
import { formatearDia, formatearDiaCorto, formatearFechaHora, hoyLima } from "../../lib/fechas";
import { puede } from "../../lib/roles";
import { useAhora } from "../../lib/useAhora";
import { claveDatos, datosApi, ingestasApi, type FuenteFrescura, type IngestaCorrida } from "../../services/datos";
import { mensajeDeError } from "../../services/httpClient";
import { useUsuario } from "../auth/AuthProvider";
import { useSeleccion } from "../catalogo/SeleccionProvider";
import {
  ETIQUETA_ESTADO_INGESTA,
  TONO_ESTADO_INGESTA,
  corridaColgada,
  corridasVisibles,
  detalleTurnos,
  diasAtraso,
  esInformativa,
  etiquetaDisparo,
  formatearDuracionMs,
  HORAS_CORRIDA_COLGADA,
  hayIngestaEnCurso,
  nombreFuente,
  ordenarFuentes,
  progresoIngesta,
  referenciaFrescura,
  resumirFrescura,
} from "./frescura";

/** Ventana de días evaluada para detectar huecos (propuesta §3.3). */
export const DIAS_VENTANA_FRESCURA = 7;
const INTERVALO_SONDEO_MS = 2500;
const CORRIDAS_VISIBLES = 6;

function listarHuecos(huecos: string[]): string {
  const muestra = huecos.slice(0, 4).map((h) => formatearDiaCorto(h));
  return huecos.length > 4 ? `${muestra.join(", ")} y ${huecos.length - 4} más` : muestra.join(", ");
}

function FilaFuente({ f, referencia }: { f: FuenteFrescura; referencia: string }) {
  const informativa = esInformativa(f);
  const verde = f.estado === "verde";
  const atraso = diasAtraso(f, referencia);
  const huecos = f.huecos ?? [];
  const lineasTurno = detalleTurnos(f);
  const Icono = informativa ? Info : verde ? CheckCircle2 : AlertTriangle;

  return (
    <li className="flex items-start gap-2.5 border-b border-borde py-2.5 last:border-b-0">
      <Icono
        className={cn("mt-0.5 size-4 shrink-0", informativa ? "text-info" : verde ? "text-ok" : "text-warn")}
        aria-hidden="true"
      />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
          <span className="text-[13px] font-medium text-texto">{nombreFuente(f.fuente, f.nombre)}</span>
          <Badge tono={informativa ? "neutro" : verde ? "exito" : "aviso"} icono={false}>
            {informativa ? "Informativo" : verde ? "Al día" : "Atrasado"}
          </Badge>
        </div>
        <span className="cifras text-xs text-texto-2">
          {f.ultima_fecha ? (
            <>
              Hasta {formatearDiaCorto(f.ultima_fecha)}
              {!informativa && atraso !== null && atraso > 0 && (
                <span className="text-warn-tx">
                  {" "}
                  · falta{atraso === 1 ? "" : "n"} {atraso} día{atraso === 1 ? "" : "s"}
                </span>
              )}
            </>
          ) : (
            "Sin datos todavía"
          )}
        </span>
        {huecos.length > 0 && (
          <span className="cifras text-xs text-warn-tx">
            Hueco{huecos.length === 1 ? "" : "s"}: {listarHuecos(huecos)}
          </span>
        )}
        {lineasTurno.length > 0 && (
          <span className="cifras text-xs text-texto-2">{lineasTurno.join("; ")}</span>
        )}
        {f.detalle && <span className="text-xs text-texto-3">{f.detalle}</span>}
      </div>
    </li>
  );
}

function FilaCorrida({ c, ahora }: { c: IngestaCorrida; ahora: Date }) {
  const error = c.errores[0];
  const colgada = corridaColgada(c, ahora);
  return (
    <li className="flex flex-col gap-0.5 border-b border-borde py-2 last:border-b-0">
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <span className="text-[13px] font-medium">{nombreFuente(c.fuente)}</span>
        {colgada ? (
          <Badge tono="aviso">Sin terminar</Badge>
        ) : (
          <Badge
            tono={TONO_ESTADO_INGESTA[c.estado]}
            icono={c.estado === "en_curso" ? <Loader2 className="animate-spin" aria-hidden="true" /> : undefined}
          >
            {ETIQUETA_ESTADO_INGESTA[c.estado]}
          </Badge>
        )}
      </div>
      <span className="cifras text-xs text-texto-2">
        {formatearFechaHora(c.inicio_at)} · {etiquetaDisparo(c)}
        {c.estado !== "en_curso" && <> · {formatearDuracionMs(c.duracion_ms)}</>}
      </span>
      {c.estado !== "en_curso" && (
        <span className="cifras text-xs text-texto-3">
          {c.desde && c.hasta && (
            <>
              {formatearDia(c.desde)} – {formatearDia(c.hasta)} ·{" "}
            </>
          )}
          {c.filas_nuevas.toLocaleString("es-PE")} nuevas · {c.filas_actualizadas.toLocaleString("es-PE")} actualizadas
          {c.conflictos > 0 && <> · {c.conflictos.toLocaleString("es-PE")} conflictos</>}
        </span>
      )}
      {colgada && (
        <span className="text-xs text-warn-tx">
          Lleva más de {HORAS_CORRIDA_COLGADA} horas sin terminar. Se cerrará al usar «Actualizar ahora».
        </span>
      )}
      {error && (
        <span className="text-xs text-err-tx">
          {error.mensaje ?? "Error sin detalle"}
          {error.status_code ? ` (HTTP ${error.status_code})` : ""}
          {c.errores.length > 1 && ` y ${c.errores.length - 1} más`}
        </span>
      )}
    </li>
  );
}

/** Panel de frescura del Dashboard: estado por fuente, «Actualizar ahora» y últimas corridas. */
export function PanelFrescura() {
  const usuario = useUsuario();
  const { modulo } = useSeleccion();
  const queryClient = useQueryClient();
  const ahora = useAhora();
  const hoy = hoyLima(ahora);
  const puedeEjecutar = puede(usuario.rol, "ejecutarIngesta");
  const verCorridas = puede(usuario.rol, "verIngestas");
  const [lanzadas, setLanzadas] = useState<number[]>([]);

  const frescura = useQuery({
    queryKey: claveDatos.frescura(modulo?.id ?? 0, hoy, DIAS_VENTANA_FRESCURA),
    queryFn: ({ signal }) => datosApi.frescura(modulo!.id, hoy, DIAS_VENTANA_FRESCURA, signal),
    enabled: !!modulo,
    staleTime: 60_000,
  });

  const corridas = useQuery({
    queryKey: claveDatos.ingestas,
    queryFn: ({ signal }) => ingestasApi.listar(20, signal),
    enabled: verCorridas,
    // Sondea solo mientras haya corridas activas: una «en_curso» de hace más de 3 h (proceso muerto)
    // no cuenta, así el panel no queda consultando sin fin ni con el botón bloqueado.
    refetchInterval: (q) => (lanzadas.length > 0 || hayIngestaEnCurso(q.state.data) ? INTERVALO_SONDEO_MS : false),
  });

  const ejecutar = useMutation({
    mutationFn: () => ingestasApi.ejecutar({}),
    onSuccess: (nuevas) => {
      setLanzadas(nuevas.map((c) => c.id));
      // Muestra de inmediato las corridas creadas (en curso) y empieza a consultar el avance.
      queryClient.setQueryData<IngestaCorrida[]>(claveDatos.ingestas, (previas = []) => [
        ...nuevas,
        ...previas.filter((p) => !nuevas.some((n) => n.id === p.id)),
      ]);
      void queryClient.invalidateQueries({ queryKey: claveDatos.ingestas });
      notificar.info("Actualización iniciada", "Se están descargando los datos de las APIs en segundo plano.");
    },
    onError: (error) => notificar.error("No se pudo iniciar la actualización", mensajeDeError(error)),
  });

  const progreso = useMemo(() => progresoIngesta(lanzadas, corridas.data ?? [], ahora), [lanzadas, corridas.data, ahora]);

  useEffect(() => {
    if (!progreso.completo) return;
    setLanzadas([]);
    void queryClient.invalidateQueries({ queryKey: claveDatos.frescuraTodo });
    if (progreso.resultado === "ok") notificar.exito("Datos actualizados", "Todas las fuentes terminaron sin errores.");
    else if (progreso.resultado === "error") notificar.error("La actualización falló", "Revisa el detalle en «Últimas corridas».");
    else notificar.info("Actualización parcial", "Alguna fuente terminó con errores. Revisa «Últimas corridas».");
  }, [progreso.completo, progreso.resultado, queryClient]);

  const enCurso = lanzadas.length > 0 || hayIngestaEnCurso(corridas.data, ahora);
  const fuentes = useMemo(() => ordenarFuentes(frescura.data?.fuentes ?? []), [frescura.data]);
  const referencia = frescura.data ? referenciaFrescura(frescura.data) : null;
  const resumen = resumirFrescura(fuentes);

  return (
    <Card>
      <CardHeader
        titulo="Frescura de datos"
        descripcion={referencia ? `Última fecha completa por fuente respecto de ayer (${formatearDiaCorto(referencia)}).` : "Última fecha completa por fuente respecto de ayer."}
        acciones={
          puedeEjecutar && (
            <Button
              tamano="sm"
              variante="secundario"
              icono={<RefreshCcw aria-hidden="true" className={cn(enCurso && "animate-spin")} />}
              onClick={() => ejecutar.mutate()}
              disabled={enCurso || ejecutar.isPending}
            >
              {enCurso ? "Actualizando…" : "Actualizar ahora"}
            </Button>
          )
        }
      />
      <CardBody className="flex flex-col gap-3">
        {lanzadas.length > 0 && (
          <div className="flex flex-col gap-1.5" role="status" aria-live="polite">
            <span className="cifras text-xs text-texto-2">
              Actualizando: {progreso.terminadas} de {progreso.total} fuente{progreso.total === 1 ? "" : "s"} terminada{progreso.total === 1 ? "" : "s"}
            </span>
            <div
              className="h-1.5 overflow-hidden rounded-full bg-sand-100"
              role="progressbar"
              aria-label="Avance de la actualización"
              aria-valuemin={0}
              aria-valuemax={progreso.total}
              aria-valuenow={progreso.terminadas}
            >
              <div
                className="h-full rounded-full bg-marca transition-[width] duration-500"
                style={{ width: `${progreso.total ? Math.max(8, (progreso.terminadas / progreso.total) * 100) : 0}%` }}
              />
            </div>
          </div>
        )}

        {!modulo ? (
          <p className="text-[13px] text-texto-2">Elige un módulo en la cabecera.</p>
        ) : frescura.isPending ? (
          <div className="flex flex-col gap-2" aria-busy="true">
            {Array.from({ length: 5 }, (_, i) => (
              <Skeleton key={i} className="h-9" />
            ))}
          </div>
        ) : frescura.isError ? (
          <Alert tono="error" titulo="No se pudo cargar la frescura">
            {mensajeDeError(frescura.error)}{" "}
            <button type="button" className="font-semibold underline" onClick={() => void frescura.refetch()}>
              Reintentar
            </button>
          </Alert>
        ) : (
          <>
            <p className={cn("flex items-center gap-1.5 text-[13px] font-medium", resumen.alDia ? "text-ok-tx" : "text-warn-tx")}>
              {resumen.alDia ? (
                <CheckCircle2 className="size-4" aria-hidden="true" />
              ) : (
                <AlertTriangle className="size-4" aria-hidden="true" />
              )}
              {resumen.alDia
                ? "Todo al día"
                : [
                    resumen.atrasadas > 0 && `${resumen.atrasadas} fuente${resumen.atrasadas === 1 ? "" : "s"} atrasada${resumen.atrasadas === 1 ? "" : "s"}`,
                    resumen.conHuecos > 0 && `${resumen.conHuecos} con huecos`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
            </p>
            <ul aria-label="Frescura por fuente">
              {fuentes.map((f) => (
                <FilaFuente key={f.fuente} f={f} referencia={referencia!} />
              ))}
            </ul>
          </>
        )}

        {verCorridas && (
          <section aria-labelledby="titulo-corridas" className="flex flex-col gap-1 border-t border-borde pt-3">
            <h4 id="titulo-corridas" className="text-[13px] font-semibold">
              Últimas corridas
            </h4>
            {corridas.isPending ? (
              <Skeleton className="h-12" />
            ) : corridas.isError ? (
              <p className="text-xs text-err-tx">No se pudieron cargar las corridas: {mensajeDeError(corridas.error)}</p>
            ) : corridas.data.length === 0 ? (
              <p className="text-xs text-texto-2">Todavía no hay corridas de ingesta.</p>
            ) : (
              <ul aria-label="Últimas corridas de ingesta">
                {corridasVisibles(corridas.data, CORRIDAS_VISIBLES).map((c) => (
                  <FilaCorrida key={c.id} c={c} ahora={ahora} />
                ))}
              </ul>
            )}
          </section>
        )}
      </CardBody>
    </Card>
  );
}
