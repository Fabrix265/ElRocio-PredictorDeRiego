import type { ReactNode } from "react";

import logoAvoperu from "../../assets/logos/avoperu.svg";
import logoTalsa from "../../assets/logos/talsa.svg";

interface AuthLayoutProps {
  titulo: string;
  descripcion?: ReactNode;
  children: ReactNode;
}

/**
 * Pantallas de acceso: panel de marca en degradado verde (logos + "Grupo El Rocío") y el
 * formulario sobre blanco. En celular, una sola columna con el panel compacto arriba.
 */
export function AuthLayout({ titulo, descripcion, children }: AuthLayoutProps) {
  return (
    <div className="grid min-h-dvh grid-cols-1 bg-superficie lg:grid-cols-2">
      <aside className="panel-marca flex flex-col justify-between gap-6 px-5 py-6 text-white sm:px-8 sm:py-8 lg:px-12 lg:py-12">
        <div className="flex flex-wrap gap-3">
          <img src={logoAvoperu} alt="Logo AvoPeru" className="h-10 w-auto sm:h-12" />
          <img src={logoTalsa} alt="Logo Talsa" className="h-10 w-auto sm:h-12" />
        </div>
        <div className="flex max-w-md flex-col gap-2.5">
          <span className="text-xs font-semibold tracking-[0.08em] text-green-100 uppercase">Grupo El Rocío</span>
          <p className="text-2xl leading-8 font-semibold text-balance sm:text-[28px] sm:leading-9">
            Plan de riego diario del módulo 5
          </p>
          <p className="hidden text-green-50 sm:block">
            Cronogramas generados con el modelo, revisados por el encargado y confirmados en campo.
          </p>
        </div>
      </aside>
      <main className="flex items-start justify-center px-4 py-8 sm:items-center sm:px-8 lg:py-12">
        <div className="flex w-full max-w-[380px] flex-col gap-5">
          <div className="flex flex-col gap-1.5">
            <h1 className="text-xl leading-7 font-semibold text-texto">{titulo}</h1>
            {descripcion && <p className="text-[13px] text-texto-2">{descripcion}</p>}
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}
