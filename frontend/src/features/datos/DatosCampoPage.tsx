import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChartLine } from "lucide-react";
import { useMemo, useState } from "react";

import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageHeader } from "../../components/ui/PageHeader";
import { Select } from "../../components/ui/Select";
import { Skeleton } from "../../components/ui/Skeleton";
import { formatearDiaCorto, hoyLima, sumarDias } from "../../lib/fechas";
import { mensajeDeError } from "../../services/httpClient";
import { claveReportes, reportesApi, type Agua, type Serie } from "../../services/reportes";
import { useUsuario } from "../auth/AuthProvider";
import { useSeleccion } from "../catalogo/SeleccionProvider";
import { COLORES, Grafico, opcionBase } from "./Grafico";

const RANGOS = [7, 14, 30] as const;
const PROFUNDIDADES = ["15", "30", "45", "60", "75", "90"] as const;

const numero = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const ejeDias = (fechas: string[]) => ({
  type: "category", data: fechas.map(formatearDiaCorto), axisTick: { show: false },
  axisLabel: { fontSize: 10, hideOverlap: true }, axisLine: { lineStyle: { color: COLORES.borde } },
});
const ejeValor = (nombre: string, extra: Record<string, unknown> = {}) => ({
  type: "value", name: nombre, nameTextStyle: { fontSize: 10, align: "left" }, axisLabel: { fontSize: 10 },
  splitLine: { lineStyle: { color: "#EDE9DF" } }, ...extra,
});

/** Suma de un campo de los turnos elegidos; null si ninguno tiene dato. */
function sumar(valores: (number | null)[]): number | null {
  const reales = valores.filter((v): v is number => v != null);
  return reales.length ? Math.round(reales.reduce((a, b) => a + b, 0) * 10) / 10 : null;
}

function opcionAgua(agua: Agua, turno: string) {
  const fechas = agua.dias.map((d) => d.fecha);
  const elegir = (campo: "aplicado_m3" | "propuesto_m3" | "modelo_m3") =>
    agua.dias.map((d) => sumar(d.turnos.filter((t) => turno === "todos" || String(t.turno_id) === turno).map((t) => t[campo])));
  const series: Record<string, unknown>[] = [
    { name: "Aplicado", type: "bar", data: elegir("aplicado_m3"), itemStyle: { color: COLORES.aplicado, borderRadius: [3, 3, 0, 0] }, barMaxWidth: 22 },
    { name: "Propuesto", type: "line", data: elegir("propuesto_m3"), itemStyle: { color: COLORES.propuesto }, lineStyle: { width: 2 }, symbolSize: 5, connectNulls: false },
  ];
  if (agua.con_modelo) {
    series.push({ name: "Modelo", type: "line", data: elegir("modelo_m3"), itemStyle: { color: COLORES.modelo }, lineStyle: { type: "dashed", width: 1.5 }, symbolSize: 4 });
  }
  return opcionBase({ xAxis: ejeDias(fechas), yAxis: ejeValor("m³"), series });
}

function opcionPlanta(planta: Serie) {
  const fechas = planta.puntos.map((p) => String(p.fecha));
  return opcionBase({
    xAxis: ejeDias(fechas),
    yAxis: [ejeValor("µm"), ejeValor("µm", { splitLine: { show: false }, nameTextStyle: { fontSize: 10, align: "right" } })],
    series: [
      { name: "MDS (contracción)", type: "line", data: planta.puntos.map((p) => numero(p.mds_contraccion_um)), itemStyle: { color: COLORES.turnos[3] }, symbolSize: 5 },
      { name: "Crecimiento del tronco", type: "bar", yAxisIndex: 1, data: planta.puntos.map((p) => numero(p.crecimiento_tronco_um)), itemStyle: { color: "#8EC39A", borderRadius: [3, 3, 0, 0] }, barMaxWidth: 18 },
    ],
  });
}

function opcionSuelo(suelo: Serie) {
  const fechas = suelo.puntos.map((p) => String(p.fecha));
  const series: Record<string, unknown>[] = PROFUNDIDADES.map((cm, i) => ({
    name: `${cm} cm`, type: "line", symbolSize: 4,
    data: suelo.puntos.map((p) => numero(p[`hum_${cm}cm_media`])),
    itemStyle: { color: [...COLORES.turnos, "#5B6B7A"][i] },
  }));
  series.push({
    name: "Línea de estrés", type: "line", symbol: "none", data: suelo.puntos.map((p) => numero(p.hum_linea_estres_media)),
    lineStyle: { type: "dashed", width: 2, color: COLORES.estres }, itemStyle: { color: COLORES.estres },
  });
  return opcionBase({ xAxis: ejeDias(fechas), yAxis: ejeValor("% vol.", { scale: true }), series });
}

function opcionClima(clima: Serie) {
  const fechas = clima.puntos.map((p) => String(p.fecha));
  return opcionBase({
    xAxis: ejeDias(fechas),
    yAxis: [ejeValor("°C", { scale: true }), ejeValor("mm", { splitLine: { show: false }, nameTextStyle: { fontSize: 10, align: "right" } })],
    series: [
      { name: "ETo", type: "bar", yAxisIndex: 1, data: clima.puntos.map((p) => numero(p.eto_mm)), itemStyle: { color: "#B9DBC0", borderRadius: [3, 3, 0, 0] }, barMaxWidth: 18 },
      { name: "Lluvia", type: "bar", yAxisIndex: 1, data: clima.puntos.map((p) => numero(p.lluvia_mm)), itemStyle: { color: COLORES.turnos[0], borderRadius: [3, 3, 0, 0] }, barMaxWidth: 18 },
      { name: "T máx", type: "line", data: clima.puntos.map((p) => numero(p.t_max)), itemStyle: { color: COLORES.turnos[1] }, symbolSize: 4 },
      { name: "T mín", type: "line", data: clima.puntos.map((p) => numero(p.t_min)), itemStyle: { color: COLORES.turnos[4] }, symbolSize: 4 },
    ],
  });
}

function Seccion({ titulo, descripcion, consulta, vacio, children }: {
  titulo: string; descripcion: string; consulta: { isPending: boolean; isError: boolean; error: unknown; isPlaceholderData?: boolean };
  vacio: boolean; children: React.ReactNode;
}) {
  return (
    <Card className="min-w-0">
      <CardHeader titulo={titulo} descripcion={descripcion} />
      <div className={consulta.isPlaceholderData ? "p-4 opacity-60" : "p-4"}>
        {consulta.isPending ? <Skeleton className="h-[260px]" />
          : consulta.isError ? <Alert tono="error">{mensajeDeError(consulta.error)}</Alert>
            : vacio ? <EmptyState compacto icono={<ChartLine />} titulo="Sin datos en este rango" />
              : children}
      </div>
    </Card>
  );
}

export default function DatosCampoPage() {
  const usuario = useUsuario();
  const { modulo } = useSeleccion();
  const ayer = sumarDias(hoyLima(), -1);
  const [dias, setDias] = useState<number>(14);
  const [turno, setTurno] = useState("todos");
  const desde = sumarDias(ayer, -(dias - 1));
  const moduloId = modulo?.id ?? 0;

  const agua = useQuery({ queryKey: claveReportes.agua(moduloId, desde, ayer), queryFn: ({ signal }) => reportesApi.agua(moduloId, desde, ayer, signal), enabled: !!modulo, placeholderData: keepPreviousData });
  const planta = useQuery({ queryKey: claveReportes.serie("planta", desde, ayer, moduloId), queryFn: ({ signal }) => reportesApi.serie("planta", desde, ayer, moduloId, signal), enabled: !!modulo, placeholderData: keepPreviousData });
  const suelo = useQuery({ queryKey: claveReportes.serie("suelo", desde, ayer, moduloId), queryFn: ({ signal }) => reportesApi.serie("suelo", desde, ayer, moduloId, signal), enabled: !!modulo, placeholderData: keepPreviousData });
  const clima = useQuery({ queryKey: claveReportes.serie("clima", desde, ayer, moduloId), queryFn: ({ signal }) => reportesApi.serie("clima", desde, ayer, moduloId, signal), enabled: !!modulo, placeholderData: keepPreviousData });

  const turnos = agua.data?.dias[0]?.turnos ?? [];
  const opciones = useMemo(() => ({
    agua: agua.data ? opcionAgua(agua.data, turno) : null,
    planta: planta.data ? opcionPlanta(planta.data) : null,
    suelo: suelo.data ? opcionSuelo(suelo.data) : null,
    clima: clima.data ? opcionClima(clima.data) : null,
  }), [agua.data, planta.data, suelo.data, clima.data, turno]);

  if (!modulo) {
    return <Card><EmptyState compacto icono={<ChartLine />} titulo="Elige un módulo" descripcion="Usa el selector Fundo › Módulo de la cabecera." /></Card>;
  }
  const sinAgua = !agua.data?.dias.some((d) => d.turnos.some((t) => t.aplicado_m3 != null || t.propuesto_m3 != null));
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        antetitulo="Operación"
        titulo="Datos de campo"
        descripcion={`Riego, planta, suelo y clima de ${modulo.codigo} del ${formatearDiaCorto(desde)} al ${formatearDiaCorto(ayer)}.`}
        acciones={
          <div className="flex gap-2" role="group" aria-label="Rango de días">
            {RANGOS.map((n) => (
              <Button key={n} tamano="sm" variante={dias === n ? "primario" : "secundario"} aria-pressed={dias === n} onClick={() => setDias(n)}>
                {n} días
              </Button>
            ))}
          </div>
        }
      />

      <Seccion
        titulo="Agua aplicada vs propuesta"
        descripcion={usuario.rol === "programador" ? "m³ por día: aplicado (barras) y versión publicada (línea)." : "m³ por día: aplicado (barras), versión publicada (línea) y propuesta del modelo (discontinua)."}
        consulta={agua}
        vacio={sinAgua}
      >
        <div className="mb-3 w-full max-w-56">
          <Select aria-label="Turno" value={turno} onValueChange={setTurno}
            opciones={[{ value: "todos", label: "Todos los turnos" }, ...turnos.map((t) => ({ value: String(t.turno_id), label: t.turno_codigo }))]} />
        </div>
        {opciones.agua && <Grafico opcion={opciones.agua} etiqueta="Agua aplicada y propuesta por día" />}
      </Seccion>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Seccion titulo="MDS y crecimiento del tronco" descripcion="Contracción diaria máxima (MDS) y crecimiento del tronco, en µm (Phytech)." consulta={planta} vacio={!planta.data?.puntos.length}>
          {opciones.planta && <Grafico opcion={opciones.planta} etiqueta="MDS y crecimiento del tronco por día" />}
        </Seccion>
        <Seccion titulo="Humedad del suelo por profundidad" descripcion="Media diaria (% vol.) a 15–90 cm y línea de estrés (discontinua)." consulta={suelo} vacio={!suelo.data?.puntos.length}>
          {opciones.suelo && <Grafico opcion={opciones.suelo} etiqueta="Humedad del suelo por profundidad y línea de estrés" />}
        </Seccion>
      </div>

      <Seccion titulo="Clima" descripcion="ETo y lluvia (mm, barras) y temperaturas máxima y mínima (°C) de la estación WeatherLink." consulta={clima} vacio={!clima.data?.puntos.length}>
        {opciones.clima && <Grafico opcion={opciones.clima} etiqueta="Clima diario: ETo, lluvia y temperaturas" />}
      </Seccion>
    </div>
  );
}
