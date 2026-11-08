import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Droplet, FileSpreadsheet, Trash2, Upload } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button, clasesBoton } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Dialog, DialogClose, DialogContent } from "../../components/ui/Dialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageHeader } from "../../components/ui/PageHeader";
import { Skeleton } from "../../components/ui/Skeleton";
import { notificar } from "../../components/ui/Toast";
import { formatearDia, formatearFechaHora } from "../../lib/fechas";
import { useAhora } from "../../lib/useAhora";
import { claveDatos } from "../../services/datos";
import { ApiError, mensajeDeError } from "../../services/httpClient";
import { claveRiego, riegoApi, type CambioAplicar, type CargaRiego } from "../../services/riego";
import {
  ETIQUETA_ESTADO_CARGA,
  ETIQUETA_RESULTADO,
  RESULTADOS,
  TONO_ESTADO_CARGA,
  contarResultados,
  esAplicable,
  formatearBytes,
  totalAAplicar,
  venceCarga,
} from "./etiquetas";
import { PasosCarga } from "./PasosCarga";
import { VistaPreviaCarga } from "./VistaPreviaCarga";

/** 409/410 al confirmar o marcar = la carga venció (24 h o cambió un registro comparado). */
export function esErrorVencida(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 409 || error.status === 410);
}

const MENSAJE_VENCIDA =
  "La vista previa venció: pasaron 24 horas o alguien cambió uno de los registros comparados. Sube el archivo otra vez para revisarlo con los datos actuales.";

function aplicarCambios(carga: CargaRiego, cambios: CambioAplicar[]): CargaRiego {
  const porId = new Map(cambios.map((c) => [c.id, c.aplicar]));
  return { ...carga, grupos: carga.grupos.map((g) => (porId.has(g.id) ? { ...g, aplicar: porId.get(g.id)! } : g)) };
}

function rangoFechas(carga: CargaRiego): string {
  if (carga.grupos.length === 0) return "—";
  let min = carga.grupos[0].fecha;
  let max = min;
  for (const g of carga.grupos) {
    if (g.fecha < min) min = g.fecha;
    if (g.fecha > max) max = g.fecha;
  }
  return min === max ? formatearDia(min) : `${formatearDia(min)} – ${formatearDia(max)}`;
}

function Encabezado({ carga, vence }: { carga: CargaRiego; vence: Date | null }) {
  return (
    <Card className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
      <div className="flex min-w-0 items-center gap-2.5">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-green-50 text-green-600" aria-hidden="true">
          <FileSpreadsheet className="size-5" />
        </span>
        <div className="flex min-w-0 flex-col">
          <span className="truncate text-[13.5px] font-semibold">{carga.archivo_nombre}</span>
          <span className="cifras text-xs text-texto-2">
            {formatearBytes(carga.tamano_bytes)} · subido {formatearFechaHora(carga.subido_at)}
            {carga.subido_por && <> por {carga.subido_por}</>} · fechas {rangoFechas(carga)}
          </span>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tono={TONO_ESTADO_CARGA[carga.estado]}>{ETIQUETA_ESTADO_CARGA[carga.estado]}</Badge>
        {carga.estado === "previsualizada" && vence && (
          <span className="cifras text-xs text-texto-2">Vence {formatearFechaHora(vence)}</span>
        )}
      </div>
    </Card>
  );
}

function Resultado({ carga }: { carga: CargaRiego }) {
  const contadores = contarResultados(carga.grupos);
  const aplicados = totalAAplicar(carga.grupos);
  return (
    <Card>
      <EmptyState
        icono={<CheckCircle2 />}
        titulo={`Carga confirmada: ${aplicados.toLocaleString("es-PE")} turno-días aplicados`}
        descripcion={
          <>
            {carga.confirmado_at && <>Confirmada el {formatearFechaHora(carga.confirmado_at)}</>}
            {carga.confirmado_por && <> por {carga.confirmado_por}</>}
            {carga.confirmado_at && ". "}
            Quedaron como riego aplicado (origen Excel) y la acción quedó en la auditoría.
          </>
        }
        accion={
          <div className="flex flex-col items-center gap-3">
            <ul className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-texto-2">
              {RESULTADOS.filter((r) => esAplicable({ resultado: r }) && contadores[r].aplicar > 0).map((r) => (
                <li key={r} className="cifras">
                  {ETIQUETA_RESULTADO[r]}: <strong className="text-texto">{contadores[r].aplicar.toLocaleString("es-PE")}</strong>
                </li>
              ))}
            </ul>
            <Link to="/riego" className={clasesBoton("primario")}>
              <Droplet aria-hidden="true" />
              Ver riego aplicado
            </Link>
          </div>
        }
      />
    </Card>
  );
}

/** Pasos 2 y 3 del asistente: vista previa, marcar grupos, confirmar o descartar. */
export default function CargaDetallePage() {
  const { id: idTexto } = useParams();
  const id = Number(idTexto);
  const idValido = Number.isInteger(id) && id > 0;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const ahora = useAhora();
  const [confirmando, setConfirmando] = useState(false);
  const [descartando, setDescartando] = useState(false);
  const [mensajeVencida, setMensajeVencida] = useState<string | null>(null);

  const consulta = useQuery({
    queryKey: claveRiego.carga(id),
    queryFn: ({ signal }) => riegoApi.carga(id, signal),
    enabled: idValido,
  });
  const carga = consulta.data;

  const alVencer = (error: unknown) => {
    setMensajeVencida(error instanceof ApiError && error.detail ? error.detail : MENSAJE_VENCIDA);
    void queryClient.invalidateQueries({ queryKey: claveRiego.carga(id) });
  };

  const marcar = useMutation({
    mutationFn: (cambios: CambioAplicar[]) => riegoApi.marcar(id, cambios),
    onMutate: async (cambios) => {
      await queryClient.cancelQueries({ queryKey: claveRiego.carga(id) });
      const previa = queryClient.getQueryData<CargaRiego>(claveRiego.carga(id));
      if (previa) queryClient.setQueryData(claveRiego.carga(id), aplicarCambios(previa, cambios));
      return { previa };
    },
    onError: (error, _cambios, contexto) => {
      if (contexto?.previa) queryClient.setQueryData(claveRiego.carga(id), contexto.previa);
      if (esErrorVencida(error)) alVencer(error);
      else notificar.error("No se pudo guardar la selección", mensajeDeError(error));
    },
    onSuccess: (actualizada) => {
      // Si hay otro cambio en vuelo, su respuesta llegará después: no se pisa la vista optimista.
      if (queryClient.isMutating({ mutationKey: ["riego", "marcar", id] }) <= 1) {
        queryClient.setQueryData(claveRiego.carga(id), actualizada);
      }
    },
    mutationKey: ["riego", "marcar", id],
  });

  const confirmar = useMutation({
    mutationFn: () => riegoApi.confirmar(id),
    onSuccess: (confirmada) => {
      setConfirmando(false);
      queryClient.setQueryData(claveRiego.carga(id), confirmada);
      void queryClient.invalidateQueries({ queryKey: claveRiego.todo, predicate: (q) => q.queryKey[1] !== "carga" });
      void queryClient.invalidateQueries({ queryKey: claveDatos.frescuraTodo });
      notificar.exito("Carga confirmada", `${totalAAplicar(confirmada.grupos).toLocaleString("es-PE")} turno-días quedaron como riego aplicado.`);
    },
    onError: (error) => {
      setConfirmando(false);
      if (esErrorVencida(error)) alVencer(error);
      else notificar.error("No se pudo confirmar la carga", mensajeDeError(error));
    },
  });

  const descartar = useMutation({
    mutationFn: () => riegoApi.descartar(id),
    onSuccess: () => {
      setDescartando(false);
      void queryClient.invalidateQueries({ queryKey: claveRiego.carga(id) });
      notificar.info("Carga descartada", "No se guardó ningún cambio.");
      navigate("/riego");
    },
    onError: (error) => {
      setDescartando(false);
      notificar.error("No se pudo descartar la carga", mensajeDeError(error));
    },
  });

  const vence = carga ? venceCarga(carga) : null;
  const vencidaPorTiempo = carga?.estado === "previsualizada" && !!vence && ahora.getTime() >= vence.getTime();
  const vencida = carga?.estado === "vencida" || vencidaPorTiempo || mensajeVencida !== null;
  const aAplicar = useMemo(() => (carga ? totalAAplicar(carga.grupos) : 0), [carga]);
  const contadores = useMemo(() => (carga ? contarResultados(carga.grupos) : null), [carga]);
  const paso = carga?.estado === "confirmada" ? 3 : 2;

  const subirOtraVez = (
    <Link to="/riego/cargas/nueva" className={clasesBoton("primario", "sm")}>
      <Upload aria-hidden="true" />
      Subir otra vez
    </Link>
  );

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        antetitulo="Riego aplicado"
        titulo={paso === 3 ? "Carga confirmada" : "Vista previa de la carga"}
        descripcion={
          paso === 3
            ? undefined
            : "Revisa qué pasará con cada turno-día. Desmarca lo que no quieras aplicar; nada se guarda hasta que confirmes."
        }
        acciones={
          <Link to="/riego" className={clasesBoton("fantasma")}>
            <ArrowLeft aria-hidden="true" />
            Volver
          </Link>
        }
      />
      <PasosCarga actual={paso} />

      {!idValido ? (
        <Alert tono="error">El enlace de la carga no es válido.</Alert>
      ) : consulta.isPending ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton className="h-14" />
          <Skeleton className="h-24" />
          <Skeleton className="h-64" />
        </div>
      ) : consulta.isError ? (
        <Alert tono="error" titulo="No se pudo cargar la vista previa">
          {mensajeDeError(consulta.error)}{" "}
          <button type="button" className="font-semibold underline" onClick={() => void consulta.refetch()}>
            Reintentar
          </button>
        </Alert>
      ) : (
        <>
          <Encabezado carga={consulta.data} vence={vence} />

          {consulta.data.estado === "confirmada" ? (
            <Resultado carga={consulta.data} />
          ) : consulta.data.estado === "descartada" ? (
            <Alert tono="info" titulo="Esta carga fue descartada">
              <div className="flex flex-col items-start gap-2">
                <span>No se guardó ningún cambio.</span>
                {subirOtraVez}
              </div>
            </Alert>
          ) : (
            <>
              {vencida && (
                <Alert tono="aviso" titulo="La carga venció">
                  <div className="flex flex-col items-start gap-2">
                    <span>{mensajeVencida ?? MENSAJE_VENCIDA}</span>
                    {subirOtraVez}
                  </div>
                </Alert>
              )}
              <VistaPreviaCarga
                grupos={consulta.data.grupos}
                bloqueada={vencida || confirmar.isPending}
                onCambiar={(cambios) => marcar.mutate(cambios)}
              />

              <div className="sticky bottom-[calc(72px+env(safe-area-inset-bottom))] z-20 rounded-lg border border-borde bg-superficie/95 px-4 py-3 shadow-elevada backdrop-blur md:bottom-4">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <p className="cifras text-[13px]" aria-live="polite">
                    Se aplicarán <strong>{aAplicar.toLocaleString("es-PE")}</strong> turno-días
                    {contadores && contadores.error.total > 0 && (
                      <span className="text-err-tx"> · {contadores.error.total.toLocaleString("es-PE")} con error no se cargan</span>
                    )}
                  </p>
                  <div className="flex gap-2">
                    <Button
                      variante="secundario"
                      icono={<Trash2 aria-hidden="true" />}
                      onClick={() => setDescartando(true)}
                      disabled={confirmar.isPending || descartar.isPending}
                      className="flex-1 sm:flex-none"
                    >
                      Descartar
                    </Button>
                    <Button
                      icono={<CheckCircle2 aria-hidden="true" />}
                      onClick={() => setConfirmando(true)}
                      disabled={vencida || aAplicar === 0 || marcar.isPending}
                      cargando={confirmar.isPending}
                      className="flex-1 sm:flex-none"
                    >
                      Confirmar
                    </Button>
                  </div>
                </div>
              </div>
            </>
          )}
        </>
      )}

      <Dialog open={confirmando} onOpenChange={(abierto) => !confirmar.isPending && setConfirmando(abierto)}>
        <DialogContent
          titulo="¿Confirmar la carga?"
          descripcion={`Se aplicarán ${aAplicar.toLocaleString("es-PE")} turno-días como riego aplicado (origen Excel). Los registros reemplazados se conservan como versiones anteriores.`}
          pie={
            <>
              <DialogClose asChild>
                <Button variante="secundario" disabled={confirmar.isPending}>
                  Cancelar
                </Button>
              </DialogClose>
              <Button cargando={confirmar.isPending} onClick={() => confirmar.mutate()}>
                Confirmar carga
              </Button>
            </>
          }
        >
          {contadores && (
            <ul className="cifras flex flex-col gap-1 text-[13px]">
              {RESULTADOS.filter((r) => esAplicable({ resultado: r })).map((r) => (
                <li key={r} className="flex justify-between gap-4">
                  <span>{ETIQUETA_RESULTADO[r]}</span>
                  <span className="font-semibold">
                    {contadores[r].aplicar.toLocaleString("es-PE")}
                    <span className="font-normal text-texto-3"> de {contadores[r].total.toLocaleString("es-PE")}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={descartando} onOpenChange={(abierto) => !descartar.isPending && setDescartando(abierto)}>
        <DialogContent
          titulo="¿Descartar la carga?"
          descripcion="No se guardará ningún cambio del archivo. Podrás subirlo otra vez cuando quieras."
          ancho="sm"
          pie={
            <>
              <DialogClose asChild>
                <Button variante="secundario" disabled={descartar.isPending}>
                  Volver
                </Button>
              </DialogClose>
              <Button variante="peligro" cargando={descartar.isPending} onClick={() => descartar.mutate()}>
                Descartar
              </Button>
            </>
          }
        />
      </Dialog>
    </div>
  );
}
