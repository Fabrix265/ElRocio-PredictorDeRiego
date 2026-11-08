import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarDays, Moon, RefreshCw } from "lucide-react";
import { useState } from "react";
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
import { Gantt } from "./Gantt";

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
      <div className="px-4">
        <Gantt turnos={version.turnos} />
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
  const usuario = useUsuario();
  const queryClient = useQueryClient();
  const [numero, setNumero] = useState<number | null>(null);
  const [confirmar, setConfirmar] = useState(false);
  const puedeRegenerar = puede(usuario.rol, "generarCronogramas");

  const consulta = useQuery({
    queryKey: claveCronogramas.detalle(id),
    queryFn: ({ signal }) => cronogramasApi.detalle(id, signal),
    enabled: Number.isInteger(id) && id > 0,
  });
  const otra = useQuery({
    queryKey: claveCronogramas.version(id, numero ?? 0),
    queryFn: ({ signal }) => cronogramasApi.version(id, numero!, signal),
    enabled: numero !== null,
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

  return (
    <div className="flex flex-col gap-4">
      <Link to="/cronogramas" className="inline-flex w-fit items-center gap-1 text-sm font-semibold text-marca hover:underline">
        <ArrowLeft className="size-4" aria-hidden="true" /> Cronogramas
      </Link>

      {consulta.isPending ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton className="h-16" />
          <Skeleton className="h-64" />
        </div>
      ) : consulta.isError ? (
        <Alert tono="error" titulo="No se pudo cargar el cronograma">
          {mensajeDeError(consulta.error)}
        </Alert>
      ) : (
        <>
          <PageHeader
            antetitulo={`Cronograma · ${c!.modulo_codigo}`}
            titulo={formatearDiaCorto(c!.fecha)}
            descripcion={
              <span className="flex flex-wrap items-center gap-2">
                <Badge tono={TONO_ESTADO[c!.estado]}>{ETIQUETA_ESTADO[c!.estado]}</Badge>
                {c!.tiene_borrador_cambios && <Badge tono="aviso">Cambios sin publicar</Badge>}
                <span className="text-xs text-texto-2">La corrección y la publicación llegan en la fase 4.</span>
              </span>
            }
            acciones={
              puedeRegenerar && (
                <Button variante="secundario" onClick={() => regenerar.mutate(false)} disabled={regenerar.isPending}>
                  <RefreshCw aria-hidden="true" className={regenerar.isPending ? "animate-spin" : undefined} />
                  {regenerar.isPending ? "Regenerando…" : "Regenerar"}
                </Button>
              )
            }
          />
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

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_280px]">
            <Card className="min-w-0">
              <CardHeader titulo={numero === null ? "Versión vigente" : `Versión v${numero}`} />
              {numero !== null && otra.isPending ? (
                <div className="p-4">
                  <Skeleton className="h-48" />
                </div>
              ) : numero !== null && otra.isError ? (
                <div className="p-4">
                  <Alert tono="error">{mensajeDeError(otra.error)}</Alert>
                </div>
              ) : version ? (
                <div className="pb-2">
                  <ContenidoVersion version={version} />
                </div>
              ) : (
                <EmptyState compacto icono={<CalendarDays />} titulo="Sin versión visible" />
              )}
            </Card>
            <Card className="h-fit">
              <CardHeader titulo="Versiones" descripcion="Toca una para verla" />
              <ListaVersiones versiones={c!.versiones} elegida={numero} onElegir={setNumero} />
            </Card>
          </div>
        </>
      )}

      <Dialog open={confirmar} onOpenChange={setConfirmar}>
        <DialogContent
          titulo="¿Regenerar sobre las correcciones?"
          descripcion="El borrador tiene correcciones. Regenerar crea una versión nueva con la propuesta del modelo; las correcciones quedan en el historial de versiones."
          pie={
            <>
              <Button variante="secundario" onClick={() => setConfirmar(false)}>
                Cancelar
              </Button>
              <Button onClick={() => regenerar.mutate(true)} disabled={regenerar.isPending}>
                Regenerar igual
              </Button>
            </>
          }
        >
          <p className="text-sm text-texto-2">Lo publicado no cambia hasta que se publique el borrador.</p>
        </DialogContent>
      </Dialog>
    </div>
  );
}
