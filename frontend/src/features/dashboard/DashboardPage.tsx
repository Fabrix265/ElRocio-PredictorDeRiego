import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { ArrowRight, CloudSun, Droplets, Sparkles } from "lucide-react";
import { Link } from "react-router";

import { Badge } from "../../components/ui/Badge";
import { Alert } from "../../components/ui/Alert";
import { Skeleton } from "../../components/ui/Skeleton";
import { mensajeDeError } from "../../services/httpClient";
import { ETIQUETA_ESTADO, TONO_ESTADO, formato, totalesPlan } from "../cronogramas/etiquetas";
import { textoEto, useEtoDiaAnterior } from "../cronogramas/useEtoDiaAnterior";
import { Card, CardBody, CardHeader } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { cn } from "../../lib/cn";
import { formatearDiaCorto, formatearFechaLarga, saludoLima } from "../../lib/fechas";
import { puede } from "../../lib/roles";
import { claveReportes, reportesApi, type Dashboard } from "../../services/reportes";
import { useUsuario } from "../auth/AuthProvider";
import { useSeleccion } from "../catalogo/SeleccionProvider";
import { kpisParaRol, pieSinRiegoAyer, type Kpi } from "./kpis";
import { HoyManana, useCronogramasHoyManana } from "./HoyManana";
import { PanelFrescura } from "./PanelFrescura";

/** Color del ícono de cada KPI (tinte suave + color fuerte); el número siempre va en texto oscuro. */
const TINTE_KPI: Record<string, string> = {
  agua_aplicada_m3ha: "bg-info-bg text-info",
  aplicado_vs_modelo_pct: "bg-green-50 text-green-600",
  mds_um: "bg-violeta-bg text-violeta",
  eto_mm: "bg-warn-bg text-ambar",
};

function TarjetaKpi({ kpi, estado, dashboard }: { kpi: Kpi; estado?: ReactNode; dashboard: UseQueryResult<Dashboard> }) {
  const Icono = kpi.icono;
  const valor = kpi.campo ? dashboard.data?.[kpi.campo] : null;
  const pie = kpi.campo === "agua_aplicada_m3ha" && dashboard.data
    ? dashboard.data.turnos_con_riego
      ? `${dashboard.data.turnos_con_riego} de ${dashboard.data.turnos_total} turnos · ${formatearNumero(dashboard.data.agua_aplicada_m3, 0)} m³`
      : pieSinRiegoAyer(dashboard.data.ultimo_riego_fecha)
    : kpi.campo === "aplicado_vs_modelo_pct"
      ? "Aplicado ayer frente a la propuesta del modelo"
      : dashboard.data ? `Ayer, ${formatearDiaCorto(dashboard.data.ayer)}` : "";
  return (
    <Card className="tarjeta-interactiva flex min-w-[68%] snap-start flex-col gap-2 px-4 py-4 min-[420px]:min-w-[46%] sm:min-w-0">
      <span className="flex items-center gap-2 text-[12.5px] font-medium text-texto-2">
        <span
          className={cn(
            "flex size-7 shrink-0 items-center justify-center rounded-lg [&_svg]:size-4",
            (kpi.campo && TINTE_KPI[kpi.campo]) || "bg-green-50 text-green-600",
          )}
          aria-hidden="true"
        >
          <Icono />
        </span>
        <span className="min-w-0 leading-4">{kpi.titulo}</span>
      </span>
      {kpi.estadoManana ? <div className="flex min-h-8 items-center">{estado}</div> : dashboard.isPending ? (
        <Skeleton className="h-8" />
      ) : dashboard.isError ? (
        <span className="text-xs text-err-tx">{mensajeDeError(dashboard.error)}</span>
      ) : (
        <>
          <span className={cn("cifras text-[28px] leading-8 font-bold tracking-[-0.02em]", valor == null ? "text-sand-300" : "text-texto")}>
            {valor == null ? "—" : formatearNumero(valor, kpi.decimales ?? 1)}
            {kpi.unidad && <small className="ml-1 text-[13px] font-semibold tracking-normal text-texto-3">{kpi.unidad}</small>}
          </span>
          <span className="text-xs leading-4 text-texto-3">{valor == null && kpi.campo !== "agua_aplicada_m3ha" ? "Sin datos de ayer" : pie}</span>
        </>
      )}
    </Card>
  );
}

const fmt = new Map<number, Intl.NumberFormat>();
function formatearNumero(valor: number | null | undefined, decimales: number): string {
  if (valor == null) return "—";
  if (!fmt.has(decimales)) fmt.set(decimales, new Intl.NumberFormat("es-PE", { minimumFractionDigits: decimales, maximumFractionDigits: decimales }));
  return fmt.get(decimales)!.format(valor);
}

/** Pronóstico Phytech de los próximos días (última captura). */
function Pronostico({ dashboard }: { dashboard: UseQueryResult<Dashboard> }) {
  const serie = dashboard.data?.pronostico;
  return (
    <Card>
      <CardHeader
        titulo="Pronóstico Phytech"
        descripcion={serie?.capturado_fecha ? `Capturado el ${formatearDiaCorto(serie.capturado_fecha)}` : "Próximos cinco días"}
      />
      <CardBody>
        {dashboard.isPending ? (
          <Skeleton className="h-24" />
        ) : dashboard.isError ? (
          <Alert tono="error">{mensajeDeError(dashboard.error)}</Alert>
        ) : !serie?.puntos.length ? (
          <EmptyState compacto icono={<CloudSun />} titulo="Sin pronóstico" descripcion="Llega con la ingesta diaria de Phytech." />
        ) : (
          <ul className="grid grid-cols-2 gap-2 @min-[480px]:grid-cols-3 @min-[760px]:grid-cols-5" aria-label="Pronóstico por día">
            {serie.puntos.map((p) => (
              <li key={String(p.fecha)} className="flex flex-col gap-1 rounded-lg border border-borde-suave bg-linear-to-b from-superficie to-hundido px-3 py-3">
                <span className="flex items-center justify-between text-xs font-semibold text-texto-2">
                  {formatearDiaCorto(String(p.fecha))}
                  <CloudSun className="size-4 text-ambar" aria-hidden="true" />
                </span>
                <span className="cifras text-xl font-bold tracking-[-0.02em] text-texto">{formatearNumero(p.t_max as number | null, 1)}<small className="ml-0.5 text-xs font-semibold text-texto-3">°C</small></span>
                <span className="cifras text-xs text-texto-2">ETo {formatearNumero(p.eto_mm as number | null, 1)} mm · HR {formatearNumero(p.humedad as number | null, 0)} %</span>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

/** Resumen del plan de hoy dentro de la portada verde: estado, m³/ha, m³ y ETo. */
function PlanDeHoy({ consulta, fecha }: { consulta: ReturnType<typeof useCronogramasHoyManana>["consultas"][number]; fecha: string }) {
  const usuario = useUsuario();
  const { modulo } = useSeleccion();
  const eto = useEtoDiaAnterior(modulo?.id, fecha);
  const c = consulta.data;
  const v = c?.version;
  return (
    <div className="flex w-full min-w-0 flex-col gap-3 rounded-lg bg-white/10 p-4 ring-1 ring-white/20 backdrop-blur-sm ring-inset lg:w-[340px]">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold tracking-[0.06em] text-green-100 uppercase">Plan de hoy · {formatearDiaCorto(fecha)}</span>
        {c && (
          <span className="inline-flex h-[22px] items-center rounded-full bg-white/15 px-2.5 text-xs font-semibold text-white ring-1 ring-white/25 ring-inset">
            {ETIQUETA_ESTADO[c.estado]}
          </span>
        )}
      </div>
      {!modulo ? (
        <p className="text-sm text-green-50">Elige un módulo para ver el plan.</p>
      ) : consulta.isPending ? (
        <div aria-hidden="true" className="flex flex-col gap-2">
          <span className="h-9 w-40 animate-pulse rounded-md bg-white/15" />
          <span className="h-4 w-56 animate-pulse rounded-md bg-white/10" />
        </div>
      ) : consulta.isError ? (
        <p className="text-sm text-green-50">{mensajeDeError(consulta.error)}</p>
      ) : !v ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-green-50">{usuario.rol === "programador" ? "Aún no hay cronograma publicado." : "Aún no hay cronograma para hoy."}</p>
          {puede(usuario.rol, "generarCronogramas") && (
            <Link to="/generar" className="inline-flex h-9 items-center gap-2 rounded-md bg-white px-3.5 text-[13px] font-semibold text-green-800 shadow-sm hover:bg-green-50">
              <Sparkles className="size-4" aria-hidden="true" /> Generar
            </Link>
          )}
        </div>
      ) : (
        <>
          <div className="flex items-end gap-2">
            <span className="cifras text-[34px] leading-9 font-bold tracking-[-0.03em]">{formato.m3ha(v.total_m3ha ?? totalesPlan(v.turnos).m3ha)}</span>
            <span className="pb-1 text-sm font-semibold text-green-100">m³/ha</span>
          </div>
          <p className="cifras flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px] text-green-50">
            <span>{formato.m3(v.total_m3)} m³</span>
            <span aria-hidden="true" className="text-green-300">·</span>
            <span>{textoEto(eto)}</span>
            <span aria-hidden="true" className="text-green-300">·</span>
            <span>{v.turnos.reduce((s, t) => s + t.n_ciclos, 0)} ciclos</span>
          </p>
          <Link
            to={`/cronogramas/${c.id}`}
            className="inline-flex h-9 w-fit items-center gap-2 rounded-md bg-white px-3.5 text-[13px] font-semibold text-green-800 shadow-sm transition-colors hover:bg-green-50 focus-visible:outline-2 focus-visible:outline-white"
          >
            Ver plan de hoy <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </>
      )}
    </div>
  );
}

export function DashboardPage() {
  const usuario = useUsuario();
  const { fundo, modulo } = useSeleccion();
  const nombre = usuario.nombre.trim().split(/\s+/)[0] || usuario.username;
  const contexto = [fundo?.nombre, modulo?.codigo].filter(Boolean).join(" · ");
  const kpis = kpisParaRol(usuario.rol);
  const dashboard = useQuery({
    queryKey: claveReportes.dashboard(modulo?.id ?? 0),
    queryFn: ({ signal }) => reportesApi.dashboard(modulo!.id, signal),
    enabled: !!modulo,
  });
  // Un único observador por fecha alimenta la portada, el KPI de mañana y «Hoy y mañana».
  const cronogramas = useCronogramasHoyManana();
  const manana = cronogramas.consultas[1];
  const estadoManana = !modulo ? (
    <span className="text-sm text-texto-2">Elige un módulo</span>
  ) : manana.isPending ? (
    <Skeleton className="h-8 w-full" />
  ) : manana.isError ? (
    <Alert tono="error">{mensajeDeError(manana.error)}</Alert>
  ) : manana.data ? (
    <Badge ajustar tono={TONO_ESTADO[manana.data.estado]}>{ETIQUETA_ESTADO[manana.data.estado]}</Badge>
  ) : (
    <span className="text-sm text-texto-2">Sin cronograma</span>
  );

  return (
    <div className="flex flex-col gap-5">
      <section
        aria-label="Resumen del día"
        className="panel-marca relative overflow-hidden rounded-xl px-5 py-6 text-white shadow-elevada sm:px-7 sm:py-7"
      >
        <Droplets className="pointer-events-none absolute -right-6 -bottom-8 size-44 text-white/[0.06]" strokeWidth={1.2} aria-hidden="true" />
        <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="flex min-w-0 flex-col gap-2">
            <span className="inline-flex items-center gap-2 text-[11px] font-semibold tracking-[0.12em] text-green-100 uppercase">
              <span className="h-[3px] w-4 rounded-full bg-lima" aria-hidden="true" />
              Dashboard{contexto ? ` · ${contexto}` : ""}
            </span>
            <h1 className="text-[26px] leading-8 font-bold tracking-[-0.02em] text-balance sm:text-[32px] sm:leading-10">
              {saludoLima()}, {nombre}
            </h1>
            <p className="text-sm text-green-50/90">{formatearFechaLarga()} · hora de Lima</p>
          </div>
          <PlanDeHoy consulta={cronogramas.consultas[0]} fecha={cronogramas.fechas[0]} />
        </div>
      </section>

      <section
        aria-label="Indicadores"
        className={cn(
          // Celular: carrusel horizontal (no apila cinco tarjetas); desde 640 px, grilla.
          "sin-barra -mx-4 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-1",
          "sm:mx-0 sm:grid sm:grid-cols-2 sm:overflow-visible sm:px-0 sm:pb-0 lg:grid-cols-3",
          kpis.length >= 5 ? "xl:grid-cols-5" : "xl:grid-cols-4",
        )}
      >
        {kpis.map((kpi) => (
          <TarjetaKpi key={kpi.titulo} kpi={kpi} estado={estadoManana} dashboard={dashboard} />
        ))}
      </section>

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="@container flex min-w-0 flex-col gap-5">
          <HoyManana {...cronogramas} />
          <Pronostico dashboard={dashboard} />
        </div>
        <PanelFrescura />
      </div>
    </div>
  );
}
