import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarDays, Moon, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";

import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { Dialog, DialogContent } from "../../components/ui/Dialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageHeader } from "../../components/ui/PageHeader";
import { Skeleton } from "../../components/ui/Skeleton";
import { cn } from "../../lib/cn";
import { formatearDiaCorto, formatearFechaHora } from "../../lib/fechas";
import { puede } from "../../lib/roles";
import { ApiError, mensajeDeError } from "../../services/httpClient";
import {
  claveCronogramas,
  cronogramasApi,
  type CronogramaDetalle,
  type TurnoCronograma,
  type VersionDetalle,
  type VersionResumen,
} from "../../services/cronogramas";
import { useUsuario } from "../auth/AuthProvider";
import { ETIQUETA_ESTADO, ETIQUETA_ORIGEN_VERSION, MarcasVersion, TONO_ESTADO, formato } from "./etiquetas";
import { BotonesExportar } from "./BotonesExportar";
import { Gantt } from "./Gantt";
import { EditorPlan } from "./EditorPlan";
import { ContextoDiaAnterior } from "./ContextoDiaAnterior";
import { AccionesCronograma } from "./AccionesCronograma";
import { Comparador, DatosCronograma, Diferencias, LineaTiempo } from "./ConsultasCronograma";

const TH = "border-b border-borde bg-hundido px-2.5 py-2 text-left text-xs font-semibold text-texto-2";
const TD = "border-b border-borde px-2.5 py-2 whitespace-nowrap";

function TablaTurnos({ turnos }: { turnos: TurnoCronograma[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead>
          <tr>
            <th className={TH}>Turno</th>
            <th className={TH}>Ciclo</th>
            <th className={TH}>Inicio</th>
            <th className={TH}>Fin</th>
            <th className={cn(TH, "text-right")}>Duración</th>
            <th className={cn(TH, "text-right")}>m³/ha</th>
            <th className={cn(TH, "text-right")}>m³</th>
          </tr>
        </thead>
        <tbody>
          {turnos.map((t) =>
            t.ciclos.map((c, i) => (
              <tr key={`${t.turno_id}-${c.ciclo}`} className={i === t.ciclos.length - 1 ? "[&>td]:border-b-borde" : "[&>td]:border-b-transparent"}>
                {i === 0 && (
                  <td className={cn(TD, "align-top")} rowSpan={t.ciclos.length}>
                    <div className="font-semibold text-texto">{t.turno_codigo}</div>
                    <div className="text-xs text-texto-2">
                      {t.n_ciclos} {t.n_ciclos === 1 ? "ciclo" : "ciclos"} · {formato.m3ha(t.total_m3ha)} m³/ha
                    </div>
                  </td>
                )}
                <td className={TD}>{c.ciclo}</td>
                <td className={TD}>{c.hora_inicio}</td>
                <td className={TD}>
                  {c.hora_fin}
                  {c.fin_dia_siguiente && (
                    <Moon className="ml-1 inline size-3.5 text-texto-3" aria-label="termina al día siguiente" />
                  )}
                </td>
                <td className={cn(TD, "text-right tabular-nums")}>{formato.min(c.duracion_min)}</td>
                <td className={cn(TD, "text-right tabular-nums")}>{formato.m3ha(c.riego_m3ha)}</td>
                <td className={cn(TD, "text-right tabular-nums")}>{formato.m3(c.riego_m3)}</td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </div>
  );
}

function ContenidoVersion({ version }: { version: VersionDetalle }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2 px-4 pt-3">
        <MarcasVersion marcas={version} />
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-texto-2 sm:grid-cols-4">
          <div>
            <dt>Versión</dt>
            <dd className="font-semibold text-texto">
              v{version.numero} · {ETIQUETA_ORIGEN_VERSION[version.origen]}
            </dd>
          </div>
          <div>
            <dt>Creada</dt>
            <dd className="text-texto">
              {formatearFechaHora(version.creado_at)}
              {version.creado_por ? ` · ${version.creado_por}` : ""}
            </dd>
          </div>
          <div>
            <dt>Agua total</dt>
            <dd className="text-texto">{formato.m3(version.total_m3)} m³</dd>
          </div>
          <div>
            <dt>Modelo</dt>
            <dd className="text-texto">{version.modelo_version ?? "—"}</dd>
          </div>
        </dl>
      </div>
      <TablaTurnos turnos={version.turnos} />
    </div>
  );
}

function ListaVersiones({
  versiones,
  elegida,
  onElegir,
}: {
  versiones: VersionResumen[];
  elegida: number | null;
  onElegir: (n: number | null) => void;
}) {
  return (
    <ul className="divide-y divide-borde" aria-label="Versiones">
      {versiones.map((v) => {
        const activa = elegida === v.numero || (elegida === null && (v.es_borrador || (v.es_publicada && !versiones.some((x) => x.es_borrador))));
        return (
          <li key={v.id}>
            <button
              type="button"
              onClick={() => onElegir(v.es_borrador ? null : v.numero)}
              aria-current={activa || undefined}
              className={cn(
                "flex w-full flex-col gap-1 px-4 py-2.5 text-left hover:bg-hundido",
                activa && "bg-activo-bg",
              )}
            >
              <span className="flex flex-wrap items-center gap-1.5 text-sm font-semibold text-texto">
                v{v.numero} · {ETIQUETA_ORIGEN_VERSION[v.origen]}
                {v.es_borrador && <Badge tono="neutro">Borrador</Badge>}
                {v.es_publicada && <Badge tono="info">Publicada</Badge>}
              </span>
              <span className="text-xs text-texto-2">
                {formatearFechaHora(v.creado_at)}
                {v.creado_por ? ` · ${v.creado_por}` : ""}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export default function CronogramaDetallePage() {
  const id = Number(useParams().id);
  return <Detalle key={id} id={id} />;
}

function Detalle({ id }: { id: number }) {
  const usuario = useUsuario();
  const queryClient = useQueryClient();
  const [numero, setNumero] = useState<number | null>(null);
  const [confirmar, setConfirmar] = useState(false);
  const [pestana, setPestana] = useState("Plan");
  const [edicion, setEdicion] = useState<CronogramaDetalle | null>(null);
  const apertura = useRef(false);
  const tabs = puede(usuario.rol, "verRevisionCronograma") ? ["Plan", "Gantt", "Datos", "Versiones", "Línea de tiempo"] : ["Plan", "Gantt"];
  useEffect(() => {
    if (!apertura.current && Number.isInteger(id) && id > 0 && puede(usuario.rol, "registrarVista")) {
      apertura.current = true;
      void cronogramasApi.vista(id).catch(() => undefined);
    }
  }, [id, usuario.rol]);
  const puedeRegenerar = puede(usuario.rol, "generarCronogramas");

  const consulta = useQuery({
    queryKey: claveCronogramas.detalle(id),
    queryFn: ({ signal }) => cronogramasApi.detalle(id, signal),
    enabled: Number.isInteger(id) && id > 0,
  });
  const otra = useQuery({
    queryKey: claveCronogramas.version(id, numero ?? 0),
    queryFn: ({ signal }) => cronogramasApi.version(id, numero!, signal),
    enabled: numero !== null && Number.isInteger(id) && id > 0,
  });

  const regenerar = useMutation({
    mutationFn: (conConfirmacion: boolean) => cronogramasApi.regenerar(id, conConfirmacion),
    onSuccess: () => {
      setConfirmar(false);
      setNumero(null);
      void queryClient.invalidateQueries({ queryKey: claveCronogramas.todo });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409 && /Confirma/i.test(e.message)) setConfirmar(true);
    },
  });

  const c: CronogramaDetalle | undefined = consulta.data;
  const version = numero !== null ? otra.data : c?.version ?? undefined;

  const vista = c?.versiones.find((v) => v.numero === c.mi_ultimo_visto_numero);
  const publicada = c?.versiones.find((v) => v.id === c.version_publicada_id);
  const editable = c && puede(usuario.rol, "corregirCronogramas") && c.version && c.version.id === (c.borrador_version_id ?? c.version_publicada_id) && (!!c.borrador_version_id || c.estado !== "borrador");
  if (!Number.isInteger(id) || id <= 0) return <Alert tono="error">Cronograma no válido.</Alert>;
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <Link to="/cronogramas" className="inline-flex w-fit items-center gap-1 text-sm font-semibold text-marca hover:underline">
        <ArrowLeft className="size-4" aria-hidden="true" /> Cronogramas
      </Link>

      {consulta.isPending ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton className="h-16" />
          <Skeleton className="h-64" />
        </div>
      ) : consulta.isError && !c ? (
        <Alert tono="error" titulo="No se pudo cargar el cronograma">
          {mensajeDeError(consulta.error)}
        </Alert>
      ) : (
        <>
          {consulta.isError && <Alert tono="error">No se pudo actualizar el detalle: {mensajeDeError(consulta.error)} <Button variante="fantasma" disabled={consulta.isFetching} onClick={() => void consulta.refetch()}>Reintentar</Button></Alert>}
          <PageHeader
            antetitulo={`Cronograma · ${c!.modulo_codigo}`}
            titulo={formatearDiaCorto(c!.fecha)}
            descripcion={
              <span className="flex flex-wrap items-center gap-2">
                <Badge tono={TONO_ESTADO[c!.estado]}>{ETIQUETA_ESTADO[c!.estado]}</Badge>
                {c!.tiene_borrador_cambios && <Badge tono="aviso">Cambios sin publicar</Badge>}
                {c!.num_publicaciones > 1 && c!.estado === "publicado" && <Badge tono="aviso">Modificado · pendiente de visto</Badge>}
              </span>
            }
            acciones={
              <div className="flex flex-wrap gap-2">
                <BotonesExportar cronogramaId={id} deshabilitado={!!edicion} />
                {puedeRegenerar && (
                  <Button variante="secundario" onClick={() => regenerar.mutate(false)} disabled={regenerar.isPending || !!edicion}>
                    <RefreshCw aria-hidden="true" className={regenerar.isPending ? "animate-spin" : undefined} />
                    {regenerar.isPending ? "Regenerando…" : "Regenerar"}
                  </Button>
                )}
              </div>
            }
          />
          <ContextoDiaAnterior fecha={c!.fecha} moduloId={c!.modulo_id} />
          {regenerar.isError && !confirmar && (
            <Alert tono="error" titulo="No se pudo regenerar">
              {mensajeDeError(regenerar.error)}
            </Alert>
          )}
          {regenerar.isSuccess && (
            <Alert tono="exito">Se creó la versión v{regenerar.data.dias_resultado[0]?.version} con el modelo.</Alert>
          )}
          {c!.version?.desactualizado && numero === null && puedeRegenerar && (
            <Alert tono="aviso" titulo="Hay datos nuevos">
              Llegaron datos de riego o de campo después de generar esta versión. Usa «Regenerar» para recalcularla.
            </Alert>
          )}

          {c!.estado === "correccion_solicitada" && <Alert tono="aviso" titulo="Corrección solicitada">
            <p className="break-words">{c!.correccion_solicitada_motivo}</p>
            <p>{c!.correccion_solicitada_por ?? "—"} · {formatearFechaHora(c!.correccion_solicitada_at)}</p>
          </Alert>}
          <AccionesCronograma cronograma={c!} bloqueado={!!edicion || regenerar.isPending} />
          {usuario.rol === "programador" && vista && publicada && vista.id !== publicada.id && <Card>
            <CardHeader titulo="Cambió desde tu Visto" />
            <div className="p-4"><Diferencias id={id} base={vista.numero} contra={publicada.numero} /></div>
          </Card>}
          <div role="tablist" aria-label="Detalle del cronograma" className="flex flex-wrap gap-1">
            {tabs.map((tab, i) => <button key={tab} type="button" role="tab" id={`tab-${i}`} aria-controls={`panel-${i}`} aria-selected={pestana === tab} tabIndex={pestana === tab ? 0 : -1}
              disabled={!!edicion && tab !== "Plan"}
              className={cn("rounded-md px-3 py-2 text-sm font-semibold disabled:opacity-50", pestana === tab ? "bg-activo-bg text-activo-tx" : "text-texto-2 hover:bg-hundido")}
              onClick={() => setPestana(tab)} onKeyDown={(e) => {
                if (edicion || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) return;
                e.preventDefault();
                const siguiente = e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : (i + (e.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
                setPestana(tabs[siguiente]); document.getElementById(`tab-${siguiente}`)?.focus();
              }}>{tab}</button>)}
          </div>
          <Card role="tabpanel" id={`panel-${tabs.indexOf(pestana)}`} aria-labelledby={`tab-${tabs.indexOf(pestana)}`} tabIndex={0}>
            {(pestana === "Plan" || pestana === "Gantt") && <>
              <CardHeader titulo={edicion ? `Corrigiendo v${edicion.version!.numero}` : numero === null ? "Versión vigente" : `Versión v${numero}`} acciones={pestana === "Plan" && numero === null && !edicion && editable && <Button disabled={regenerar.isPending} onClick={() => setEdicion(c!)}>Corregir</Button>} />
              {numero !== null && !edicion && <div className="px-4 pt-3"><Button variante="secundario" onClick={() => setNumero(null)}>Volver a la versión vigente</Button></div>}
              {edicion ? (
                <EditorPlan cronograma={edicion} alCerrar={() => setEdicion(null)} alRecargar={() => consulta.refetch()} />
              ) : numero !== null && otra.isPending ? (
                <div className="p-4"><Skeleton className="h-48" /></div>
              ) : numero !== null && otra.isError ? (
                <div className="p-4">
                  <Alert tono="error">
                    {mensajeDeError(otra.error)}
                    <Button variante="fantasma" disabled={otra.isFetching} onClick={() => void otra.refetch()}>Reintentar</Button>
                  </Alert>
                </div>
              ) : !version ? (
                <EmptyState compacto icono={<CalendarDays />} titulo="Sin versión visible" />
              ) : !version.turnos.length ? (
                <EmptyState compacto icono={<CalendarDays />} titulo="Sin turnos en esta versión" />
              ) : pestana === "Gantt" ? (
                <div className="p-4"><Gantt turnos={version.turnos} /></div>
              ) : (
                <div className="pb-2"><ContenidoVersion version={version} /></div>
              )}
            </>}
            {pestana === "Datos" && <DatosCronograma id={id} />}
            {pestana === "Versiones" && <>
              <CardHeader titulo="Versiones" descripcion="Toca una para verla en Plan" />
              {c!.versiones.length ? <ListaVersiones versiones={c!.versiones} elegida={numero} onElegir={(n) => { setNumero(n); setPestana("Plan"); }} /> : <p className="p-4 text-texto-2">Sin versiones visibles.</p>}
              <Comparador cronograma={c!} />
            </>}
            {pestana === "Línea de tiempo" && <LineaTiempo id={id} />}
          </Card>
        </>
      )}

      <Dialog open={confirmar} onOpenChange={(v) => { if (!regenerar.isPending) setConfirmar(v); }}>
        <DialogContent
          titulo="¿Regenerar sobre las correcciones?"
          descripcion="El borrador tiene correcciones. Regenerar crea una versión nueva con la propuesta del modelo; las correcciones quedan en el historial de versiones."
          pie={
            <>
              <Button variante="secundario" disabled={regenerar.isPending} onClick={() => setConfirmar(false)}>
                Cancelar
              </Button>
              <Button onClick={() => regenerar.mutate(true)} disabled={regenerar.isPending || !!edicion}>
                Regenerar igual
              </Button>
            </>
          }
        >
          <p className="text-sm text-texto-2">Lo publicado no cambia hasta que se publique el borrador.</p>
          {regenerar.isError && !(regenerar.error instanceof ApiError && regenerar.error.status === 409 && /Confirma/i.test(regenerar.error.message)) && <Alert tono="error">{mensajeDeError(regenerar.error)}</Alert>}
        </DialogContent>
      </Dialog>
    </div>
  );
}
