import { useEffect, useRef } from "react";

import { cn } from "../../lib/cn";

/** Colores de la propuesta (§6): distinguibles con daltonismo. */
export const COLORES = {
  turnos: ["#1F63B0", "#D17400", "#2BA37A", "#8F2A5C", "#8A7FD0"],
  propuesto: "#2A7042",
  aplicado: "#5B6B7A",
  modelo: "#D07A00",
  estres: "#C8291F",
  texto: "#5F5849",
  borde: "#DDD7C9",
};

type Opcion = Record<string, unknown>;

// ECharts se carga aparte (solo esta pantalla lo usa) y con los módulos mínimos.
let cargando: Promise<typeof import("echarts/core")> | null = null;
function cargarEcharts() {
  cargando ??= (async () => {
    const [core, charts, componentes, render] = await Promise.all([
      import("echarts/core"),
      import("echarts/charts"),
      import("echarts/components"),
      import("echarts/renderers"),
    ]);
    core.use([
      charts.BarChart, charts.LineChart, componentes.GridComponent, componentes.TooltipComponent,
      componentes.LegendComponent, componentes.MarkLineComponent, render.SVGRenderer,
    ]);
    return core;
  })();
  return cargando;
}

/** Base común: tipografía, grilla con margen para ejes y tooltip por eje. */
export function opcionBase(extra: Opcion): Opcion {
  return {
    textStyle: { fontFamily: "IBM Plex Sans, system-ui, sans-serif", color: COLORES.texto },
    grid: { left: 8, right: 12, top: 56, bottom: 8, containLabel: true },
    tooltip: { trigger: "axis", confine: true },
    legend: { top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { fontSize: 11 } },
    ...extra,
  };
}

/** Gráfico ECharts que se adapta al ancho de su contenedor. */
export function Grafico({ opcion, alto = 260, etiqueta, className }: { opcion: Opcion; alto?: number; etiqueta: string; className?: string }) {
  const nodo = useRef<HTMLDivElement>(null);
  const instancia = useRef<{ setOption: (o: Opcion, n?: boolean) => void; resize: () => void; dispose: () => void } | null>(null);

  useEffect(() => {
    let vivo = true;
    let observador: ResizeObserver | null = null;
    void cargarEcharts().then((echarts) => {
      if (!vivo || !nodo.current) return;
      instancia.current = echarts.init(nodo.current, undefined, { renderer: "svg" });
      instancia.current.setOption(opcion, true);
      observador = new ResizeObserver(() => instancia.current?.resize());
      observador.observe(nodo.current);
    });
    return () => {
      vivo = false;
      observador?.disconnect();
      instancia.current?.dispose();
      instancia.current = null;
    };
    // La instancia se crea una vez; los cambios de opción van en el efecto de abajo.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    instancia.current?.setOption(opcion, true);
  }, [opcion]);

  return <div ref={nodo} role="img" aria-label={etiqueta} className={cn("w-full min-w-0", className)} style={{ height: alto }} />;
}
