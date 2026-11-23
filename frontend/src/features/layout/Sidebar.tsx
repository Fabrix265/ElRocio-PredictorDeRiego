import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { NavLink, useMatch } from "react-router";

import { Tooltip } from "../../components/ui/Tooltip";
import { cn } from "../../lib/cn";
import { useUsuario } from "../auth/AuthProvider";
import { BotonInstalar } from "./AvisosPwa";
import { Marca } from "./Marca";
import { itemsParaRol, type ItemNav } from "./navegacion";

export function EnlaceNav({ item, colapsada, alNavegar }: { item: ItemNav; colapsada?: boolean; alNavegar?: () => void }) {
  const Icono = item.icono;
  // El estado activo se calcula aquí y la clase va como texto: con el menú colapsado, el Tooltip
  // (Radix, asChild) une clases como cadenas y convertiría una función de clase en su código fuente.
  const activo = useMatch({ path: item.ruta, end: item.ruta === "/" }) !== null;
  return (
    <Tooltip texto={item.etiqueta} desactivado={!colapsada}>
      <NavLink
        to={item.ruta}
        end={item.ruta === "/"}
        onClick={alNavegar}
        aria-label={colapsada ? item.etiqueta : undefined}
        className={cn(
          "group flex h-10 items-center gap-2.5 rounded-[10px] text-[13.5px] transition-[background,color,box-shadow] duration-150",
          "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-foco",
          colapsada ? "mx-auto w-10 justify-center px-0" : "px-3",
          activo
            ? "bg-marca bg-[image:var(--degradado-marca)] font-semibold text-white shadow-marca"
            : "font-medium text-texto-2 hover:bg-activo-bg hover:text-activo-tx",
        )}
      >
        <Icono className="size-[18px] shrink-0" strokeWidth={1.75} aria-hidden="true" />
        {!colapsada && <span className="truncate">{item.etiqueta}</span>}
      </NavLink>
    </Tooltip>
  );
}

/** Lista de navegación agrupada (operación / gestión) según el rol. */
function TituloGrupo({ texto, colapsada }: { texto: string; colapsada?: boolean }) {
  return colapsada ? (
    <li role="separator" aria-hidden="true" className="mx-2 my-2 h-px bg-borde" />
  ) : (
    <li aria-hidden="true" className="px-3 pt-4 pb-1.5 text-[10.5px] font-semibold tracking-[0.12em] text-texto-3 uppercase first:pt-0">
      {texto}
    </li>
  );
}

export function ListaNav({ colapsada, alNavegar }: { colapsada?: boolean; alNavegar?: () => void }) {
  const usuario = useUsuario();
  const items = itemsParaRol(usuario.rol);
  const operacion = items.filter((i) => i.grupo === "operacion");
  const gestion = items.filter((i) => i.grupo === "gestion");
  return (
    <ul className="flex flex-col gap-1">
      {gestion.length > 0 && !colapsada && <TituloGrupo texto="Operación" />}
      {operacion.map((item) => (
        <li key={item.ruta}>
          <EnlaceNav item={item} colapsada={colapsada} alNavegar={alNavegar} />
        </li>
      ))}
      {gestion.length > 0 && <TituloGrupo texto="Gestión" colapsada={colapsada} />}
      {gestion.map((item) => (
        <li key={item.ruta}>
          <EnlaceNav item={item} colapsada={colapsada} alNavegar={alNavegar} />
        </li>
      ))}
    </ul>
  );
}

interface SidebarProps {
  colapsada: boolean;
  alternar: () => void;
}

/** Barra lateral blanca de escritorio: 248 px, colapsable a 72 px. */
export function Sidebar({ colapsada, alternar }: SidebarProps) {
  return (
    <aside
      className={cn(
        "sticky top-0 hidden h-dvh shrink-0 flex-col border-r border-borde bg-sidebar py-5 transition-[width] duration-200 md:flex",
        colapsada ? "w-[var(--sidebar-ancho-colapsado)] px-3" : "w-[var(--sidebar-ancho)] px-3",
      )}
    >
      <div className="pb-6">
        <Marca compacta={colapsada} />
      </div>
      <nav aria-label="Principal" className="min-h-0 flex-1 overflow-y-auto">
        <ListaNav colapsada={colapsada} />
      </nav>
      <div className="flex flex-col gap-2 border-t border-borde pt-3">
        <BotonInstalar compacto={colapsada} />
        <Tooltip texto="Expandir menú" desactivado={!colapsada}>
          <button
            type="button"
            onClick={alternar}
            aria-expanded={!colapsada}
            aria-label={colapsada ? "Expandir menú" : "Colapsar menú"}
            className={cn(
              "flex h-9 w-full items-center gap-2.5 rounded-md text-[13px] text-texto-2 hover:bg-activo-bg hover:text-activo-tx",
              "focus-visible:outline-2 focus-visible:outline-foco",
              colapsada ? "justify-center" : "px-2.5",
            )}
          >
            {colapsada ? (
              <PanelLeftOpen className="size-[18px]" strokeWidth={1.75} aria-hidden="true" />
            ) : (
              <>
                <PanelLeftClose className="size-[18px]" strokeWidth={1.75} aria-hidden="true" />
                <span>Colapsar menú</span>
              </>
            )}
          </button>
        </Tooltip>
      </div>
    </aside>
  );
}
