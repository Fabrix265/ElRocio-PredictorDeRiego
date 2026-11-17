import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChartLine, Download } from "lucide-react";
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
import { csvAgua, turnosElegidos, valorAgua, type SerieAgua, type UnidadAgua } from "./agua";
import { COLORES, Grafico, opcionBase } from "./Grafico";
import { TablaAgua } from "./TablaAgua";

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

function opcionAgua(agua: Agua, turno: string, unidad: UnidadAgua) {
  const fechas = agua.dias.map((d) => d.fecha);
  const elegir = (serie: SerieAgua) => agua.dias.map((d) => valorAgua(turnosElegidos(d, turno), serie, unidad));
  const series: Record<string, unknown>[] = [
    { name: "Real", type: "bar", stack: "riego", data: elegir("real"), itemStyle: { color: COLORES.aplicado }, barMaxWidth: 22 },
    { name: "Provisional (sin dato real)", type: "bar", stack: "riego", data: elegir("provisional"),
      itemStyle: { color: COLORES.provisional, borderColor: COLORES.aplicado, borderType: "dashed", borderWidth: 1 }, barMaxWidth: 22 },
    { name: agua.con_modelo ? "Modelo modificado (publicado)" : "Plan publicado", type: "line", data: elegir("propuesto"), itemStyle: { color: COLORES.propuesto }, lineStyle: { width: 2 }, symbolSize: 5, connectNulls: false },
  ];
  if (agua.con_modelo) {
    series.push({ name: "Modelo", type: "line", data: elegir("modelo"), itemStyle: { color: COLORES.modelo }, lineStyle: { type: "dashed", width: 1.5 }, symbolSize: 4 });
  }
  return opcionBase({ xAxis: ejeDias(fechas), yAxis: ejeValor(unidad === "m3ha" ? "m³/ha" : "m³"), series });
}

function opcionPlanta(planta: Serie) {
  const fechas = planta.puntos.map((p) => String(p.fecha));
  return opcionBase({
    xAxis: ejeDias(fechas),
    yAxis: [
      ejeValor("MDS µm", { nameTextStyle: { fontSize: 10, align: "left", color: COLORES.turnos[3] }, axisLabel: { fontSize: 10, color: COLORES.turnos[3] } }),
      ejeValor("Crecimiento µm", { splitLine: { show: false }, nameTextStyle: { fontSize: 10, align: "right", color: COLORES.crecimiento }, axisLabel: { fontSize: 10, color: COLORES.crecimiento } }),
    ],
    series: [
      { name: "MDS (contracción)", type: "line", data: planta.puntos.map((p) => numero(p.mds_contraccion_um)), itemStyle: { color: COLORES.turnos[3] }, symbolSize: 5 },
      { name: "Crecimiento del tronco", type: "bar", yAxisIndex: 1, data: planta.puntos.map((p) => numero(p.crecimiento_tronco_um)), itemStyle: { color: COLORES.crecimientoBarra, borderRadius: [3, 3, 0, 0] }, barMaxWidth: 18 },
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
      { name: "Lluvia", type: "bar", yAxisIndex: 1, data: clima.puntos.map((p) => numero(p.lluvia_mm)), itemStyle: { color: COLORES.lluvia, borderRadius: [3, 3, 0, 0] }, barMaxWidth: 18 },
      { name: "T máx", type: "line", data: clima.puntos.map((p) => numero(p.t_max)), itemStyle: { color: COLORES.tMax }, lineStyle: { width: 2 }, symbol: "circle", symbolSize: 5 },
      { name: "T mín", type: "line", data: clima.puntos.map((p) => numero(p.t_min)), itemStyle: { color: COLORES.tMin }, lineStyle: { width: 2, type: "dashed" }, symbol: "triangle", symbolSize: 6 },
    ],
  });
}

function descargarCsv(contenido: string, nombre: string) {
  const url = URL.createObjectURL(new Blob([contenido], { type: "text/csv;charset=utf-8" }));
  const enlace = document.createElement("a");
  enlace.href = url;
  enlace.download = nombre.replace(/[^\w.-]+/g, "_");
  enlace.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
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
  const [unidad, setUnidad] = useState<UnidadAgua>("m3ha");
  const desde = sumarDias(ayer, -(dias - 1));
  const moduloId = modulo?.id ?? 0;

  const agua = useQuery({ queryKey: claveReportes.agua(moduloId, desde, ayer), queryFn: ({ signal }) => reportesApi.agua(moduloId, desde, ayer, signal), enabled: !!modulo, placeholderData: keepPreviousData });
  const planta = useQuery({ queryKey: claveReportes.serie("planta", desde, ayer, moduloId), queryFn: ({ signal }) => reportesApi.serie("planta", desde, ayer, moduloId, signal), enabled: !!modulo, placeholderData: keepPreviousData });
  const suelo = useQuery({ queryKey: claveReportes.serie("suelo", desde, ayer, moduloId), queryFn: ({ signal }) => reportesApi.serie("suelo", desde, ayer, moduloId, signal), enabled: !!modulo, placeholderData: keepPreviousData });
  const clima = useQuery({ queryKey: claveReportes.serie("clima", desde, ayer, moduloId), queryFn: ({ signal }) => reportesApi.serie("clima", desde, ayer, moduloId, signal), enabled: !!modulo, placeholderData: keepPreviousData });

  const turnos = agua.data?.dias[0]?.turnos ?? [];
  const opciones = useMemo(() => ({
    agua: agua.data ? opcionAgua(agua.data, turno, unidad) : null,
    planta: planta.data ? opcionPlanta(planta.data) : null,
    suelo: suelo.data ? opcionSuelo(suelo.data) : null,
    clima: clima.data ? opcionClima(clima.data) : null,
  }), [agua.data, planta.data, suelo.data, clima.data, turno, unidad]);

  if (!modulo) {
    return <Card><EmptyState compacto icono={<ChartLine />} titulo="Elige un módulo" descripcion="Usa el selector Fundo › Módulo de la cabecera." /></Card>;
  }
  const sinAgua = !agua.data?.dias.some((d) => d.turnos.some((t) => t.aplicado_m3 != null || t.propuesto_m3 != null || t.modelo_m3 != null));
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
        titulo="Riego: real, modelo y modificado"
        descripcion={usuario.rol === "programador"
          ? "Por día: riego real del controlador (barras) y plan publicado (línea)."
          : "Por día: riego real del controlador (barras), lo que propuso el modelo (discontinua) y el modelo modificado que se publicó (línea)."}
        consulta={agua}
        vacio={sinAgua}
      >
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="w-full max-w-56">
            <Select aria-label="Turno" value={turno} onValueChange={setTurno}
              opciones={[{ value: "todos", label: "Todos los turnos" }, ...turnos.map((t) => ({ value: String(t.turno_id), label: t.turno_codigo }))]} />
          </div>
          <div className="w-full max-w-40">
            <Select aria-label="Unidad" value={unidad} onValueChange={(v) => setUnidad(v as UnidadAgua)}
              opciones={[{ value: "m3ha", label: "m³/ha" }, { value: "m3", label: "m³" }]} />
          </div>
        </div>
        {opciones.agua && <Grafico opcion={opciones.agua} etiqueta="Riego real, del modelo y modificado por día" />}
        <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-texto-2" aria-label="Cómo leer el gráfico de agua">
          <li><strong>Real:</strong> lo que registró el controlador (o el histórico).</li>
          <li><strong>Provisional:</strong> lo planificado mientras no llega el dato real.</li>
          <li><strong>{agua.data?.con_modelo ? "Modelo modificado" : "Plan publicado"}:</strong> la versión publicada al programador{agua.data?.con_modelo ? " (igual al modelo si no hubo cambios)" : ""}.</li>
          {agua.data?.con_modelo && <li><strong>Modelo:</strong> lo que propuso el modelo antes de las correcciones.</li>}
          {unidad === "m3ha" && turno === "todos" && <li>Con todos los turnos, m³/ha = m³ totales ÷ hectáreas de los turnos con dato.</li>}
        </ul>
        {agua.data && <div className="mt-4 flex flex-col gap-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold text-texto">Detalle por día y turno</h3>
            <Button tamano="sm" variante="secundario" onClick={() => descargarCsv(csvAgua(agua.data.dias, unidad, agua.data.con_modelo), `riego_${modulo.codigo}_${desde}_${ayer}.csv`)}>
              <Download aria-hidden="true" /> Descargar CSV
            </Button>
          </div>
          <TablaAgua dias={agua.data.dias} unidad={unidad} conModelo={agua.data.con_modelo} turno={turno} />
        </div>}
      </Seccion>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Seccion titulo="MDS y crecimiento del tronco" descripcion="Contracción diaria máxima (MDS, eje izquierdo) y crecimiento del tronco (eje derecho), en µm (Phytech)." consulta={planta} vacio={!planta.data?.puntos.length}>
          {opciones.planta && <Grafico opcion={opciones.planta} etiqueta="MDS y crecimiento del tronco por día" />}
        </Seccion>
        <Seccion titulo="Humedad del suelo por profundidad" descripcion="Media diaria (% vol.) a 15–90 cm de la sonda Phytech y su línea de estrés (discontinua): por debajo de ella la planta empieza a estresarse." consulta={suelo} vacio={!suelo.data?.puntos.length}>
          {opciones.suelo && <Grafico opcion={opciones.suelo} etiqueta="Humedad del suelo por profundidad y línea de estrés" />}
        </Seccion>
      </div>

      <Seccion titulo="Clima" descripcion="ETo y lluvia (mm, barras) y temperaturas máxima y mínima (°C) de la estación WeatherLink." consulta={clima} vacio={!clima.data?.puntos.length}>
        {opciones.clima && <Grafico opcion={opciones.clima} etiqueta="Clima diario: ETo, lluvia y temperaturas" />}
      </Seccion>
    </div>
  );
}
