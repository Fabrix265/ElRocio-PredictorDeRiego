import { Activity, CalendarClock, Droplet, Gauge, ThermometerSun, type LucideIcon } from "lucide-react";

import type { Rol } from "../../lib/roles";

/** Campo de `Dashboard` que muestra el KPI (el estado de mañana se arma aparte). */
export type CampoKpi = "agua_aplicada_m3ha" | "aplicado_vs_modelo_pct" | "mds_um" | "eto_mm";

export interface Kpi {
  titulo: string;
  icono: LucideIcon;
  fase: number;
  unidad: string;
  campo?: CampoKpi;
  decimales?: number;
  estadoManana?: boolean;
  /** Roles que lo ven; sin `roles`, todos. */
  roles?: readonly Rol[];
}

/** El programador ve solo lo publicado, nunca la propuesta del modelo (propuesta §4). */
const ROLES_CON_MODELO: readonly Rol[] = ["admin", "encargado", "subgerente"];

export const KPIS: Kpi[] = [
  { titulo: "Agua aplicada ayer", icono: Droplet, fase: 5, unidad: "m³/ha", campo: "agua_aplicada_m3ha", decimales: 1 },
  { titulo: "Aplicado vs modelo", icono: Gauge, fase: 5, unidad: "%", roles: ROLES_CON_MODELO, campo: "aplicado_vs_modelo_pct", decimales: 0 },
  { titulo: "MDS (contracción del tronco)", icono: Activity, fase: 5, unidad: "µm", campo: "mds_um", decimales: 0 },
  { titulo: "ETo de ayer", icono: ThermometerSun, fase: 5, unidad: "mm", campo: "eto_mm", decimales: 2 },
  { titulo: "Estado de mañana", icono: CalendarClock, fase: 4, unidad: "", estadoManana: true },
];

/** KPIs visibles para un rol. */
export function kpisParaRol(rol: Rol): Kpi[] {
  return KPIS.filter((k) => !k.roles || k.roles.includes(rol));
}
