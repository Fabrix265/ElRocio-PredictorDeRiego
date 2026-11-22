import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Check, CheckCircle2, Droplets, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardBody, CardHeader } from "../../components/ui/Card";
import { Dialog, DialogContent } from "../../components/ui/Dialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { Field } from "../../components/ui/Field";
import { Input } from "../../components/ui/Input";
import { PageHeader } from "../../components/ui/PageHeader";
import { Skeleton } from "../../components/ui/Skeleton";
import { notificar } from "../../components/ui/Toast";
import { cn } from "../../lib/cn";
import { formatearDia, formatearFechaHora } from "../../lib/fechas";
import { puede } from "../../lib/roles";
import {
  claveCopiloto,
  copilotoApi,
  type Alerta,
  type EstadoSugerencia,
  type PlanDia,
  type Sugerencia,
} from "../../services/copiloto";
import { ApiError, mensajeDeError } from "../../services/httpClient";
import { useUsuario } from "../auth/AuthProvider";
import { useSeleccion } from "../catalogo/SeleccionProvider";
import {
  ETIQUETA_ESTADO_SUGERENCIA,
  ETIQUETA_SEVERIDAD,
  ETIQUETA_TIPO,
  TONO_ESTADO_SUGERENCIA,
  TONO_SEVERIDAD,
  nombreAgente,
  ordenarPorSeveridad,
} from "./etiquetas";

const fmt = new Map<number, Intl.NumberFormat>();
function numero(valor: number | null | undefined, decimales = 1): string {
  if (valor == null) return "—";
  if (!fmt.has(decimales)) fmt.set(decimales, new Intl.NumberFormat("es-PE", { minimumFractionDigits: decimales, maximumFractionDigits: decimales }));
  return fmt.get(decimales)!.format(valor);
}

function FilaAlerta({ alerta }: { alerta: Alerta }) {
  const contexto = [alerta.turno_codigo, alerta.fecha ? formatearDia(alerta.fecha) : null].filter(Boolean).join(" · ");
  return (
    <li className="flex flex-col gap-1.5 border-b border-borde py-3 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tono={TONO_SEVERIDAD[alerta.severidad]}>{ETIQUETA_SEVERIDAD[alerta.severidad]}</Badge>
        <span className="min-w-0 text-sm font-semibold text-texto">{alerta.titulo}</span>
      </div>
      <p className="text-[13px] leading-5 text-texto-2">{alerta.detalle}</p>
      {contexto && <span className="text-xs text-texto-3">{contexto}</span>}
    </li>
  );
}

function ResumenPlan({ titulo, plan }: { titulo: string; plan: PlanDia | null }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-borde bg-superficie px-3 py-2.5">
      <span className="text-xs font-semibold text-texto-2">{titulo}</span>
      {plan ? (
        <>
          <Link to={`/cronogramas/${plan.cronograma_id}`} className="cifras text-lg font-bold text-texto hover:text-activo-tx">
            {numero(plan.total_m3, 0)}<small className="ml-0.5 text-xs font-medium text-texto-3">m³</small>
            <span className="mx-1.5 text-texto-3">·</span>
            {numero(plan.total_m3ha, 1)}<small className="ml-0.5 text-xs font-medium text-texto-3">m³/ha</small>
          </Link>
          <span className="cifras text-xs text-texto-2">
            ETo día anterior {numero(plan.eto_dia_anterior_mm, 1)} mm{plan.eto_dia_anterior_es_pronostico ? " (pronóstico)" : ""}
          </span>
          <span className="text-xs text-texto-3 first-letter:uppercase">{plan.estado_texto}</span>
        </>
      ) : (
        <span className="text-sm text-texto-3">Sin cronograma</span>
      )}
    </div>
  );
}

type Decision = { sugerencia: Sugerencia; aprobar: boolean } | null;

function TarjetaSugerencia({ s, puedeResolver, onDecidir }: {
  s: Sugerencia;
  puedeResolver: boolean;
  onDecidir: (aprobar: boolean) => void;
}) {
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-borde bg-superficie px-4 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tono={TONO_ESTADO_SUGERENCIA[s.estado]}>{ETIQUETA_ESTADO_SUGERENCIA[s.estado]}</Badge>
        <Badge tono="marca" icono={false}>{ETIQUETA_TIPO[s.tipo]}</Badge>
        {s.turno_codigo && <Badge tono="neutro" icono={false}>{s.turno_codigo}</Badge>}
        <span className="text-xs text-texto-3">{formatearDia(s.fecha)}</span>
      </div>
      <p className="text-sm font-semibold text-texto">{s.titulo}</p>
      {s.detalle && <p className="text-[13px] leading-5 whitespace-pre-line text-texto-2">{s.detalle}</p>}
      <span className="text-xs text-texto-3">
        Propuesta por {nombreAgente(s.propuesta_por)} el {formatearFechaHora(s.created_at)}
        {s.resuelto_por && ` · ${ETIQUETA_ESTADO_SUGERENCIA[s.estado].toLowerCase()} por ${s.resuelto_por}`}
        {s.comentario_resolucion && `: «${s.comentario_resolucion}»`}
      </span>
      {puedeResolver && s.estado === "pendiente" && (
        <div className="flex flex-wrap gap-2 pt-1">
          <Button tamano="sm" icono={<Check aria-hidden="true" />} onClick={() => onDecidir(true)}>Aprobar</Button>
          <Button tamano="sm" variante="secundario" icono={<X aria-hidden="true" />} onClick={() => onDecidir(false)}>Descartar</Button>
        </div>
      )}
    </li>
  );
}

function DialogoDecision({ decision, onCerrar }: { decision: Decision; onCerrar: () => void }) {
  const qc = useQueryClient();
  const [comentario, setComentario] = useState("");
  const aprobar = decision?.aprobar ?? true;
  const resolver = useMutation({
    mutationFn: () => aprobar
      ? copilotoApi.aprobar(decision!.sugerencia.id, comentario.trim())
      : copilotoApi.descartar(decision!.sugerencia.id, comentario.trim()),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: claveCopiloto.todo });
      notificar.exito(aprobar ? "Sugerencia aprobada" : "Sugerencia descartada");
      setComentario("");
      onCerrar();
    },
  });
  const conflicto = resolver.error instanceof ApiError && resolver.error.status === 409;
  const textoValido = aprobar ? comentario.trim().length <= 500 : comentario.trim().length >= 3 && comentario.trim().length <= 500;
  return (
    <Dialog open={!!decision} onOpenChange={(abierto) => { if (!abierto && !resolver.isPending) { resolver.reset(); setComentario(""); onCerrar(); } }}>
      <DialogContent
        titulo={aprobar ? "Aprobar sugerencia" : "Descartar sugerencia"}
        descripcion={aprobar
          ? "Aprobar no cambia el plan ni el riego: deja constancia de que la atiendes (por ejemplo, regenerar desde Cronogramas o revisar en campo)."
          : "Queda registrado quién la descartó y por qué."}
        pie={<>
          <Button variante="secundario" disabled={resolver.isPending} onClick={onCerrar}>Cancelar</Button>
          <Button variante={aprobar ? "primario" : "peligro"} disabled={resolver.isPending || !textoValido || conflicto}
            onClick={() => resolver.mutate()}>{resolver.isPending ? "Guardando…" : aprobar ? "Aprobar" : "Descartar"}</Button>
        </>}
      >
        <div className="flex flex-col gap-3">
          {decision && <p className="text-sm font-semibold text-texto">{decision.sugerencia.titulo}</p>}
          <Field label={aprobar ? "Comentario (opcional)" : "Motivo"} requerido={!aprobar} ayuda="Hasta 500 caracteres.">
            <Input value={comentario} maxLength={500} disabled={resolver.isPending} onChange={(e) => setComentario(e.target.value)} />
          </Field>
          {resolver.isError && <Alert tono="error">
            {conflicto ? "Otra persona ya resolvió esta sugerencia. Cierra para ver el estado actual." : mensajeDeError(resolver.error)}
          </Alert>}
        </div>
      </DialogContent>
    </Dialog>
  );
}

const FILTROS: { valor: EstadoSugerencia | "todas"; etiqueta: string }[] = [
  { valor: "pendiente", etiqueta: "Pendientes" },
  { valor: "todas", etiqueta: "Todas" },
];

export function CopilotoPage() {
  const usuario = useUsuario();
  const { modulo } = useSeleccion();
  const [filtro, setFiltro] = useState<EstadoSugerencia | "todas">("pendiente");
  const [decision, setDecision] = useState<Decision>(null);
  const puedeResolver = puede(usuario.rol, "resolverSugerencias");
  const resumen = useQuery({
    queryKey: claveCopiloto.resumen(modulo?.id ?? 0),
    queryFn: ({ signal }) => copilotoApi.resumen(modulo!.id, signal),
    enabled: !!modulo,
  });
  const sugerencias = useQuery({
    queryKey: claveCopiloto.sugerencias(modulo?.id ?? 0, filtro),
    queryFn: ({ signal }) => copilotoApi.sugerencias(modulo!.id, filtro, signal),
    enabled: !!modulo,
  });
  const alertas = ordenarPorSeveridad(resumen.data?.alertas ?? []);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        antetitulo="Copiloto"
        titulo="Copiloto agrónomo"
        descripcion="Alertas calculadas cada día con los datos del fundo y sugerencias del agente. Nada cambia el plan ni el riego sin tu decisión."
      />

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader
            titulo="Alertas de hoy"
            descripcion={resumen.data ? `${resumen.data.modulo.codigo} · calculadas el ${formatearFechaHora(resumen.data.generado_at)}` : "Plan, datos, estrés y respuesta del suelo"}
          />
          <CardBody>
            {!modulo ? (
              <EmptyState compacto icono={<Bot />} titulo="Elige un módulo" />
            ) : resumen.isPending ? (
              <Skeleton className="h-32" />
            ) : resumen.isError ? (
              <Alert tono="error">{mensajeDeError(resumen.error)}</Alert>
            ) : (
              <div className="flex flex-col gap-3">
                <div className="grid grid-cols-1 gap-2 min-[420px]:grid-cols-2">
                  <ResumenPlan titulo="Plan de hoy" plan={resumen.data.plan_hoy} />
                  <ResumenPlan titulo="Plan de mañana" plan={resumen.data.plan_manana} />
                </div>
                {alertas.length === 0 ? (
                  <EmptyState compacto icono={<CheckCircle2 />} titulo="Sin alertas" descripcion="Todo en orden con los datos de hoy." />
                ) : (
                  <ul aria-label="Alertas">{alertas.map((a, i) => <FilaAlerta key={`${a.codigo}-${a.turno_codigo ?? ""}-${i}`} alerta={a} />)}</ul>
                )}
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            titulo="Sugerencias del agente"
            descripcion={puedeResolver ? "Apruébalas o descártalas: quedan en la auditoría." : "Solo el encargado o el administrador las resuelven."}
          />
          <CardBody className="flex flex-col gap-3">
            <div role="group" aria-label="Filtrar sugerencias" className="flex gap-1.5">
              {FILTROS.map((f) => (
                <button key={f.valor} type="button" aria-pressed={filtro === f.valor} onClick={() => setFiltro(f.valor)}
                  className={cn("h-8 rounded-full border px-3 text-xs font-medium transition-colors",
                    filtro === f.valor ? "border-green-500 bg-activo-bg text-activo-tx" : "border-borde text-texto-2 hover:bg-activo-bg")}>
                  {f.etiqueta}
                </button>
              ))}
            </div>
            {!modulo ? null : sugerencias.isPending ? (
              <Skeleton className="h-24" />
            ) : sugerencias.isError ? (
              <Alert tono="error">{mensajeDeError(sugerencias.error)}</Alert>
            ) : sugerencias.data.length === 0 ? (
              <EmptyState compacto icono={<Droplets />} titulo={filtro === "pendiente" ? "Sin sugerencias pendientes" : "Aún no hay sugerencias"}
                descripcion="El agente las propone cuando detecta algo que conviene revisar." />
            ) : (
              <ul className="flex flex-col gap-2" aria-label="Sugerencias">
                {sugerencias.data.map((s) => (
                  <TarjetaSugerencia key={s.id} s={s} puedeResolver={puedeResolver}
                    onDecidir={(aprobar) => setDecision({ sugerencia: s, aprobar })} />
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>

      <DialogoDecision decision={decision} onCerrar={() => setDecision(null)} />
    </div>
  );
}

export default CopilotoPage;
