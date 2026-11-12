import { useQuery } from "@tanstack/react-query";
import { createContext, useContext, type ReactNode } from "react";
import { Badge } from "../../components/ui/Badge";
import { formatearDiaCorto, listaDias, sumarDias } from "../../lib/fechas";
import { claveReportes, reportesApi, type Serie } from "../../services/reportes";
import { useSeleccion } from "../catalogo/SeleccionProvider";

type Punto = Serie["puntos"][number];
const CAMPOS_CLIMA = ["eto_mm", "t_max", "hr_media", "lluvia_mm"];
const numero = (valor: Punto[string] | undefined): number | null => typeof valor === "number" && Number.isFinite(valor) ? valor : null;
const puntoDia = (serie: Serie | undefined, fecha: string) => serie?.puntos.find((p) => p.fecha === fecha);
const tieneClima = (p: Punto | undefined) => CAMPOS_CLIMA.some((campo) => numero(p?.[campo]) !== null);
const formato = new Intl.NumberFormat("es-PE", { maximumFractionDigits: 1 });

function useContextoRango(desde: string, hasta: string, moduloId: number) {
  const clima = useQuery({
    queryKey: claveReportes.serie("clima", desde, hasta, moduloId),
    queryFn: ({ signal }) => reportesApi.serie("clima", desde, hasta, moduloId, signal),
    enabled: !!moduloId, staleTime: 60_000,
  });
  const planta = useQuery({
    queryKey: claveReportes.serie("planta", desde, hasta, moduloId),
    queryFn: ({ signal }) => reportesApi.serie("planta", desde, hasta, moduloId, signal),
    enabled: !!moduloId, staleTime: 60_000,
  });
  const faltaClima = clima.isSuccess && listaDias(desde, hasta).some((fecha) => !tieneClima(puntoDia(clima.data, fecha)));
  const pronostico = useQuery({
    queryKey: claveReportes.serie("pronostico", desde, hasta, 0),
    queryFn: ({ signal }) => reportesApi.pronostico(desde, hasta, signal),
    enabled: !!moduloId && faltaClima, staleTime: 60_000,
  });
  return { clima, planta, pronostico, habilitado: !!moduloId };
}

const ContextoRango = createContext<ReturnType<typeof useContextoRango> | null>(null);

/** Un único observador por fuente cubre todos los días del resultado de generación. */
export function RangoContextoDiaAnterior({ fechas, moduloId, children }: { fechas: string[]; moduloId: number; children: ReactNode }) {
  const ordenadas = [...fechas].sort();
  const datos = useContextoRango(sumarDias(ordenadas[0] ?? "", -1), sumarDias(ordenadas.at(-1) ?? "", -1), fechas.length ? moduloId : 0);
  return <ContextoRango.Provider value={datos}>{children}</ContextoRango.Provider>;
}

export function ContextoDiaAnterior({ fecha, moduloId }: { fecha: string; moduloId?: number }) {
  const compartido = useContext(ContextoRango);
  return compartido ? <Franja fecha={fecha} datos={compartido} /> : <ContextoIndividual fecha={fecha} moduloId={moduloId} />;
}

function ContextoIndividual({ fecha, moduloId }: { fecha: string; moduloId?: number }) {
  const { modulo } = useSeleccion();
  const anterior = sumarDias(fecha, -1);
  const datos = useContextoRango(anterior, anterior, moduloId ?? modulo?.id ?? 0);
  return <Franja fecha={fecha} datos={datos} />;
}

function Franja({ fecha, datos }: { fecha: string; datos: ReturnType<typeof useContextoRango> }) {
  const anterior = sumarDias(fecha, -1);
  const real = puntoDia(datos.clima.data, anterior);
  const medido = tieneClima(real);
  const pronostico = medido ? undefined : puntoDia(datos.pronostico.data, anterior);
  const planta = puntoDia(datos.planta.data, anterior);
  const valores: [string, string, number | null][] = [
    ["ETo", "mm", numero(medido ? real?.eto_mm : pronostico?.eto_mm)],
    ["T máx", "°C", numero(medido ? real?.t_max : pronostico?.t_max)],
    ["HR media", "%", numero(medido ? real?.hr_media : pronostico?.humedad)],
    ["Lluvia", "mm", numero(medido ? real?.lluvia_mm : undefined)],
    ["MDS", "µm", numero(planta?.mds_contraccion_um)],
  ];
  const hayDatos = valores.some(([, , valor]) => valor !== null);
  const esPronostico = !medido && valores.slice(0, 3).some(([, , valor]) => valor !== null);
  const cargando = datos.habilitado && (datos.clima.isPending || datos.planta.isPending || (!medido && datos.pronostico.isFetching));
  const error = datos.clima.isError || datos.planta.isError || (!medido && datos.pronostico.isError);
  return <section className="min-w-0 rounded-md border border-borde bg-hundido/50 px-3 py-2" aria-label={`Día anterior a ${formatearDiaCorto(fecha)}`}>
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <h3 className="font-semibold text-texto-2">Día anterior · {formatearDiaCorto(anterior)}</h3>
      {esPronostico && <Badge tono="info">Pronóstico</Badge>}
      {cargando && <span className="text-texto-3" role="status">Cargando datos…</span>}
      {!hayDatos && !cargando && !error && <span className="text-texto-3">Sin datos del día anterior</span>}
      {error && <span className="text-err-tx">No se pudieron cargar todos los datos del día anterior.</span>}
    </div>
    {hayDatos && <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs">
      {valores.map(([etiqueta, unidad, valor]) => <div key={etiqueta} className="flex gap-1">
        <dt className="text-texto-2">{etiqueta} ({unidad})</dt>
        <dd className="cifras font-semibold text-texto">{valor === null ? "—" : formato.format(valor)}</dd>
      </div>)}
    </dl>}
  </section>;
}
