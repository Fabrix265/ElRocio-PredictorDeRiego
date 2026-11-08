import { Activity, CalendarClock, Droplet, Gauge, ThermometerSun, type LucideIcon } from "lucide-react";

import type { Rol } from "../../lib/roles";

export interface Kpi {
  titulo: string;
  icono: LucideIcon;
  fase: number;
  unidad: string;
  estadoManana?: boolean;
  /** Roles que lo ven; sin `roles`, todos. */
  roles?: readonly Rol[];
}

/** El programador ve solo lo publicado, nunca la propuesta del modelo (propuesta §4). */
const ROLES_CON_MODELO: readonly Rol[] = ["admin", "encargado", "subgerente"];

export const KPIS: Kpi[] = [
  { titulo: "Agua aplicada ayer", icono: Droplet, fase: 5, unidad: "m³/ha" },
  { titulo: "Aplicado vs modelo", icono: Gauge, fase: 5, unidad: "%", roles: ROLES_CON_MODELO },
  { titulo: "MDS (contracción del tronco)", icono: Activity, fase: 5, unidad: "µm" },
  { titulo: "ETo de ayer", icono: ThermometerSun, fase: 5, unidad: "mm" },
  { titulo: "Estado de mañana", icono: CalendarClock, fase: 4, unidad: "", estadoManana: true },
];

/** KPIs visibles para un rol (F5 hereda la regla al conectar los datos). */
export function kpisParaRol(rol: Rol): Kpi[] {
  return KPIS.filter((k) => !k.roles || k.roles.includes(rol));
}
