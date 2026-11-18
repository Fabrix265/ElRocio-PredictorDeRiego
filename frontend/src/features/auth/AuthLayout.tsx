import type { ReactNode } from "react";

import logoAvoperu from "../../assets/logos/avoperu.webp";
import logoJordie from "../../assets/logos/jordie.webp";
import logoTalsa from "../../assets/logos/talsa.webp";

/** Empresas del grupo; los archivos vienen recortados y con fondo blanco. */
const LOGOS = [
  { src: logoAvoperu, alt: "AvoPerú" },
  { src: logoTalsa, alt: "Talsa" },
  { src: logoJordie, alt: "Jordie Inversiones" },
] as const;

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
        <ul
          aria-label="Empresas del grupo"
          className="grid w-full max-w-md grid-cols-[1fr_1fr_1.45fr] divide-x divide-borde rounded-2xl bg-white px-1 py-3 shadow-lg shadow-green-900/25 ring-1 ring-white/70 sm:px-2 sm:py-4"
        >
          {LOGOS.map((logo) => (
            <li key={logo.alt} className="flex h-14 items-center justify-center px-2.5 sm:h-20 sm:px-4">
              <img src={logo.src} alt={logo.alt} className="max-h-full max-w-full object-contain" />
            </li>
          ))}
        </ul>
        <div className="flex max-w-md flex-col gap-2.5">
          <span className="text-xs font-semibold tracking-[0.08em] text-green-100 uppercase">Grupo El Rocío</span>
          <p className="text-2xl leading-8 font-semibold text-balance sm:text-[28px] sm:leading-9">
            Plan de riego diario
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
