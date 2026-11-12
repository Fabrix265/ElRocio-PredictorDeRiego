import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { CloudSun } from "lucide-react";

import { Badge } from "../../components/ui/Badge";
import { Alert } from "../../components/ui/Alert";
import { Skeleton } from "../../components/ui/Skeleton";
import { mensajeDeError } from "../../services/httpClient";
import { ETIQUETA_ESTADO, TONO_ESTADO } from "../cronogramas/etiquetas";
import { Card, CardBody, CardHeader } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageHeader } from "../../components/ui/PageHeader";
import { cn } from "../../lib/cn";
import { formatearDiaCorto, formatearFechaLarga, saludoLima } from "../../lib/fechas";
import { claveReportes, reportesApi, type Dashboard } from "../../services/reportes";
import { useUsuario } from "../auth/AuthProvider";
import { useSeleccion } from "../catalogo/SeleccionProvider";
import { kpisParaRol, pieSinRiegoAyer, type Kpi } from "./kpis";
import { HoyManana, useCronogramasHoyManana } from "./HoyManana";
import { PanelFrescura } from "./PanelFrescura";

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
    <Card className="flex flex-col gap-1.5 px-4 py-3.5">
      <span className="flex items-center gap-1.5 text-xs text-texto-2">
        <Icono className="size-3.5 text-green-500" aria-hidden="true" />
        {kpi.titulo}
      </span>
      {kpi.estadoManana ? estado : dashboard.isPending ? (
        <Skeleton className="h-8" />
      ) : dashboard.isError ? (
        <span className="text-xs text-err-tx">{mensajeDeError(dashboard.error)}</span>
      ) : (
        <>
          <span className={cn("cifras text-[26px] leading-8 font-bold tracking-tight", valor == null ? "text-sand-300" : "text-texto")}>
            {valor == null ? "—" : formatearNumero(valor, kpi.decimales ?? 1)}
            {kpi.unidad && <small className="ml-1 text-[13px] font-medium text-texto-3">{kpi.unidad}</small>}
          </span>
          <span className="text-xs text-texto-3">{valor == null && kpi.campo !== "agua_aplicada_m3ha" ? "Sin datos de ayer" : pie}</span>
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
              <li key={String(p.fecha)} className="flex flex-col gap-1 rounded-lg border border-borde bg-superficie px-3 py-2.5">
                <span className="text-xs font-semibold text-texto capitalize">{formatearDiaCorto(String(p.fecha))}</span>
                <span className="cifras text-lg font-bold text-texto">{formatearNumero(p.t_max as number | null, 1)}<small className="ml-0.5 text-xs font-medium text-texto-3">°C</small></span>
                <span className="cifras text-xs text-texto-2">ETo {formatearNumero(p.eto_mm as number | null, 1)} mm · HR {formatearNumero(p.humedad as number | null, 0)} %</span>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
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
  // Un único observador por fecha alimenta tanto el KPI como «Hoy y mañana».
  const cronogramas = useCronogramasHoyManana();
  const manana = cronogramas.consultas[1];
  const estadoManana = !modulo ? (
    <span className="text-sm text-texto-2">Elige un módulo</span>
  ) : manana.isPending ? (
    <Skeleton className="h-8" />
  ) : manana.isError ? (
    <Alert tono="error">{mensajeDeError(manana.error)}</Alert>
  ) : manana.data ? (
    <Badge ajustar tono={TONO_ESTADO[manana.data.estado]}>{ETIQUETA_ESTADO[manana.data.estado]}</Badge>
  ) : (
    <span className="text-sm text-texto-2">Sin cronograma</span>
  );

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        antetitulo="Dashboard"
        titulo={`${saludoLima()}, ${nombre}`}
        descripcion={`${formatearFechaLarga()}${contexto ? ` · ${contexto}` : ""}`}
      />

      <section aria-label="Indicadores" className={`grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 lg:grid-cols-3 ${kpis.length >= 5 ? "xl:grid-cols-5" : "xl:grid-cols-4"}`}>
        {kpis.map((kpi) => (
          <TarjetaKpi key={kpi.titulo} kpi={kpi} estado={estadoManana} dashboard={dashboard} />
        ))}
      </section>

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="@container flex min-w-0 flex-col gap-4">
          <HoyManana {...cronogramas} />
          <Pronostico dashboard={dashboard} />
        </div>
        <PanelFrescura />
      </div>
    </div>
  );
}
