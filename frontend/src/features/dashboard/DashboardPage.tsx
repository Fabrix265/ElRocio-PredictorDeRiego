import type { ReactNode } from "react";
import { CloudSun } from "lucide-react";

import { Badge } from "../../components/ui/Badge";
import { Card, CardBody, CardHeader } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatearFechaLarga, saludoLima } from "../../lib/fechas";
import { useUsuario } from "../auth/AuthProvider";
import { useSeleccion } from "../catalogo/SeleccionProvider";
import { kpisParaRol, type Kpi } from "./kpis";
import { HoyManana } from "./HoyManana";
import { PanelFrescura } from "./PanelFrescura";

function TarjetaKpi({ kpi }: { kpi: Kpi }) {
  const Icono = kpi.icono;
  return (
    <Card className="flex flex-col gap-1.5 px-4 py-3.5">
      <span className="flex items-center gap-1.5 text-xs text-texto-2">
        <Icono className="size-3.5 text-green-500" aria-hidden="true" />
        {kpi.titulo}
      </span>
      <span className="cifras text-[26px] leading-8 font-bold tracking-tight text-sand-300" aria-label="Sin datos">
        —{kpi.unidad && <small className="ml-1 text-[13px] font-medium text-texto-3">{kpi.unidad}</small>}
      </span>
      <span className="text-xs text-texto-3">Se activa en la fase {kpi.fase}</span>
    </Card>
  );
}

function TarjetaPendiente({
  titulo,
  icono,
  fase,
  descripcion,
}: {
  titulo: string;
  icono: ReactNode;
  fase: number;
  descripcion: string;
}) {
  return (
    <Card>
      <CardHeader titulo={titulo} acciones={<Badge tono="neutro">Fase {fase}</Badge>} />
      <CardBody>
        <EmptyState compacto icono={icono} titulo={`Se activa en la fase ${fase}`} descripcion={descripcion} />
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

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        antetitulo="Dashboard"
        titulo={`${saludoLima()}, ${nombre}`}
        descripcion={`${formatearFechaLarga()}${contexto ? ` · ${contexto}` : ""}`}
      />

      <section aria-label="Indicadores" className={`grid grid-cols-1 gap-3 min-[420px]:grid-cols-2 lg:grid-cols-3 ${kpis.length >= 5 ? "xl:grid-cols-5" : "xl:grid-cols-4"}`}>
        {kpis.map((kpi) => (
          <TarjetaKpi key={kpi.titulo} kpi={kpi} />
        ))}
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1.6fr_1fr]">
        <HoyManana />
        <PanelFrescura />
      </div>

      <TarjetaPendiente
        titulo="Pronóstico Phytech"
        icono={<CloudSun />}
        fase={5}
        descripcion="Temperatura máxima, ETo y humedad de los próximos cinco días."
      />
    </div>
  );
}
