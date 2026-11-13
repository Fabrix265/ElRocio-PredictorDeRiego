import { CalendarDays, ChartLine, Droplet, LayoutDashboard, ShieldCheck, SlidersHorizontal, Sparkles, Users, type LucideIcon } from "lucide-react";

import { puedeVer, type Pantalla, type Rol } from "../../lib/roles";

export interface ItemNav {
  pantalla: Pantalla;
  ruta: string;
  etiqueta: string;
  /** Etiqueta corta para el menú inferior del celular. */
  corta: string;
  icono: LucideIcon;
  grupo: "operacion" | "gestion";
}

/** Ítems de la barra lateral en orden; cada rol ve solo los suyos (propuesta §4). */
export const ITEMS_NAV: ItemNav[] = [
  { pantalla: "dashboard", ruta: "/", etiqueta: "Dashboard", corta: "Inicio", icono: LayoutDashboard, grupo: "operacion" },
  { pantalla: "generar", ruta: "/generar", etiqueta: "Generar", corta: "Generar", icono: Sparkles, grupo: "operacion" },
  { pantalla: "cronogramas", ruta: "/cronogramas", etiqueta: "Cronogramas", corta: "Cronogramas", icono: CalendarDays, grupo: "operacion" },
  { pantalla: "riego", ruta: "/riego", etiqueta: "Riego aplicado", corta: "Riego", icono: Droplet, grupo: "operacion" },
  { pantalla: "datos", ruta: "/datos", etiqueta: "Datos de campo", corta: "Datos", icono: ChartLine, grupo: "operacion" },
  { pantalla: "parametros", ruta: "/parametros-riego", etiqueta: "Parámetros de riego", corta: "Parámetros", icono: SlidersHorizontal, grupo: "gestion" },
  { pantalla: "auditoria", ruta: "/auditoria", etiqueta: "Auditoría", corta: "Auditoría", icono: ShieldCheck, grupo: "gestion" },
  { pantalla: "usuarios", ruta: "/usuarios", etiqueta: "Usuarios", corta: "Usuarios", icono: Users, grupo: "gestion" },
];

export function itemsParaRol(rol: Rol): ItemNav[] {
  return ITEMS_NAV.filter((item) => puedeVer(rol, item.pantalla));
}

/** Hasta tres accesos directos en el menú inferior del celular (el cuarto botón abre el menú). */
export function itemsInferiores(rol: Rol): ItemNav[] {
  const preferidos: Pantalla[] = ["dashboard", "cronogramas", "riego", "datos"];
  return itemsParaRol(rol)
    .filter((i) => preferidos.includes(i.pantalla))
    .slice(0, 3);
}
