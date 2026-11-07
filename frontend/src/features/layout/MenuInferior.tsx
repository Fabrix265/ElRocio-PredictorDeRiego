import * as DialogPrimitive from "@radix-ui/react-dialog";
import { KeyRound, LogOut, Menu, X } from "lucide-react";
import { useState } from "react";
import { NavLink, useNavigate } from "react-router";

import { cn } from "../../lib/cn";
import { ETIQUETA_ROL } from "../../lib/roles";
import { useAuth, useUsuario } from "../auth/AuthProvider";
import { Avatar, Marca } from "./Marca";
import { itemsInferiores } from "./navegacion";
import { ListaNav } from "./Sidebar";

const clasesItem =
  "flex flex-1 flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-medium focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-foco";

/** Celular: menú inferior con accesos directos y un cajón con todo el menú y la cuenta. */
export function MenuInferior() {
  const usuario = useUsuario();
  const { cerrarSesion } = useAuth();
  const navigate = useNavigate();
  const [abierto, setAbierto] = useState(false);
  const atajos = itemsInferiores(usuario.rol);

  return (
    <>
      <nav
        aria-label="Accesos rápidos"
        className="fixed inset-x-0 bottom-0 z-30 flex border-t border-borde bg-superficie pb-[env(safe-area-inset-bottom)] md:hidden"
      >
        {atajos.map((item) => {
          const Icono = item.icono;
          return (
            <NavLink
              key={item.ruta}
              to={item.ruta}
              end={item.ruta === "/"}
              className={({ isActive }) => cn(clasesItem, isActive ? "text-marca" : "text-texto-3")}
            >
              {({ isActive }) => (
                <>
                  <span className={cn("flex h-7 w-12 items-center justify-center rounded-full", isActive && "bg-green-50")}>
                    <Icono className="size-[18px]" strokeWidth={isActive ? 2.1 : 1.75} aria-hidden="true" />
                  </span>
                  {item.corta}
                </>
              )}
            </NavLink>
          );
        })}
        <DialogPrimitive.Root open={abierto} onOpenChange={setAbierto}>
          <DialogPrimitive.Trigger className={cn(clasesItem, "text-texto-3")}>
            <span className="flex h-7 w-12 items-center justify-center rounded-full">
              <Menu className="size-[18px]" strokeWidth={1.75} aria-hidden="true" />
            </span>
            Menú
          </DialogPrimitive.Trigger>
          <DialogPrimitive.Portal>
            <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-green-900/40" />
            <DialogPrimitive.Content
              aria-describedby={undefined}
              className="fixed inset-y-0 left-0 z-50 flex w-[min(86vw,320px)] flex-col border-r border-borde bg-sidebar px-3 py-4 shadow-elevada focus:outline-none"
            >
              <div className="flex items-center justify-between pb-4">
                <Marca />
                <DialogPrimitive.Close
                  className="inline-flex size-9 items-center justify-center rounded-md text-texto-2 hover:bg-activo-bg focus-visible:outline-2 focus-visible:outline-foco"
                  aria-label="Cerrar menú"
                >
                  <X className="size-5" aria-hidden="true" />
                </DialogPrimitive.Close>
              </div>
              <DialogPrimitive.Title className="sr-only">Menú principal</DialogPrimitive.Title>
              <nav aria-label="Principal" className="min-h-0 flex-1 overflow-y-auto">
                <ListaNav alNavegar={() => setAbierto(false)} />
              </nav>
              <div className="flex flex-col gap-1 border-t border-borde pt-3">
                <div className="flex items-center gap-2.5 rounded-lg bg-green-50 p-2.5">
                  <Avatar nombre={usuario.nombre} />
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate text-[13px] font-semibold">{usuario.nombre}</span>
                    <span className="text-[11px] text-texto-2">{ETIQUETA_ROL[usuario.rol]}</span>
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setAbierto(false);
                    navigate("/cambiar-password");
                  }}
                  className="flex h-10 items-center gap-2.5 rounded-md px-2.5 text-[13.5px] text-texto-2 hover:bg-activo-bg hover:text-activo-tx focus-visible:outline-2 focus-visible:outline-foco"
                >
                  <KeyRound className="size-[18px]" strokeWidth={1.75} aria-hidden="true" />
                  Cambiar contraseña
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setAbierto(false);
                    void cerrarSesion();
                  }}
                  className="flex h-10 items-center gap-2.5 rounded-md px-2.5 text-[13.5px] text-texto-2 hover:bg-activo-bg hover:text-activo-tx focus-visible:outline-2 focus-visible:outline-foco"
                >
                  <LogOut className="size-[18px]" strokeWidth={1.75} aria-hidden="true" />
                  Cerrar sesión
                </button>
              </div>
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        </DialogPrimitive.Root>
      </nav>
    </>
  );
}
