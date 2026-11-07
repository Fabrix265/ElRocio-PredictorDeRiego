import type { ReactNode } from "react";

import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";

interface PlaceholderPageProps {
  titulo: string;
  descripcion: string;
  fase: number;
  icono: ReactNode;
  /** Qué traerá la pantalla cuando se active. */
  detalle: string;
}

/** Pantalla protegida por rol que todavía no se implementa (se activa en una fase posterior). */
export function PlaceholderPage({ titulo, descripcion, fase, icono, detalle }: PlaceholderPageProps) {
  return (
    <div className="flex flex-col gap-4">
      <PageHeader antetitulo={titulo} titulo={titulo} descripcion={descripcion} />
      <Card>
        <EmptyState icono={icono} titulo={`Disponible en la fase ${fase}`} descripcion={detalle} />
      </Card>
    </div>
  );
}
