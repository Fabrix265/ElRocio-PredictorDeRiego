import { ChevronDown, KeyRound, LogOut } from "lucide-react";
import { useNavigate } from "react-router";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../../components/ui/DropdownMenu";
import { ETIQUETA_ROL } from "../../lib/roles";
import { useAuth, useUsuario } from "../auth/AuthProvider";
import { Avatar } from "./Marca";

export function MenuUsuario() {
  const usuario = useUsuario();
  const { cerrarSesion } = useAuth();
  const navigate = useNavigate();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="flex items-center gap-2 rounded-full py-1 pr-2 pl-1 hover:bg-activo-bg focus-visible:outline-2 focus-visible:outline-foco data-[state=open]:bg-activo-bg"
        aria-label={`Menú de ${usuario.nombre}`}
      >
        <Avatar nombre={usuario.nombre} />
        <span className="hidden min-w-0 flex-col text-left leading-tight lg:flex">
          <span className="max-w-40 truncate text-[13px] font-semibold text-texto">{usuario.nombre}</span>
          <span className="text-[11px] text-texto-3">{ETIQUETA_ROL[usuario.rol]}</span>
        </span>
        <ChevronDown className="hidden size-4 text-texto-2 lg:block" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>
          <span className="block text-[13px] font-semibold text-texto">{usuario.nombre}</span>
          <span className="block">
            {usuario.username} · {ETIQUETA_ROL[usuario.rol]}
          </span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem icono={<KeyRound aria-hidden="true" />} onSelect={() => navigate("/cambiar-password")}>
          Cambiar contraseña
        </DropdownMenuItem>
        <DropdownMenuItem
          icono={<LogOut aria-hidden="true" />}
          onSelect={() => void cerrarSesion()}
        >
          Cerrar sesión
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
