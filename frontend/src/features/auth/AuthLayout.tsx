import { CalendarCheck2, CloudSun, Droplets } from "lucide-react";
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

/** Qué hace el sistema, en tres líneas (solo desde escritorio). */
const PUNTOS = [
  { icono: Droplets, texto: "Plan diario por turno con m³, m³/ha y ETo" },
  { icono: CloudSun, texto: "Clima, suelo y planta al día para decidir" },
  { icono: CalendarCheck2, texto: "Revisado por el encargado y confirmado en campo" },
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
    <div className="grid min-h-dvh grid-cols-1 bg-superficie lg:grid-cols-[1.05fr_1fr]">
      <aside className="panel-marca relative flex flex-col justify-between gap-6 overflow-hidden px-5 py-6 text-white sm:px-8 sm:py-8 lg:px-12 lg:py-12">
        <Droplets
          className="pointer-events-none absolute -right-16 -bottom-16 hidden size-[340px] text-white/[0.05] lg:block"
          strokeWidth={1}
          aria-hidden="true"
        />
        <ul
          aria-label="Empresas del grupo"
          className="relative grid w-full max-w-md grid-cols-[1fr_1fr_1.45fr] divide-x divide-borde rounded-2xl bg-white px-1 py-3 shadow-lg shadow-green-900/25 ring-1 ring-white/70 sm:px-2 sm:py-4"
        >
          {LOGOS.map((logo) => (
            <li key={logo.alt} className="flex h-14 items-center justify-center px-2.5 sm:h-20 sm:px-4">
              <img src={logo.src} alt={logo.alt} className="max-h-full max-w-full object-contain" />
            </li>
          ))}
        </ul>
        <div className="relative flex max-w-md flex-col gap-3">
          <span className="inline-flex items-center gap-2 text-xs font-semibold tracking-[0.12em] text-green-100 uppercase">
            <span className="h-[3px] w-5 rounded-full bg-lima" aria-hidden="true" />
            Grupo El Rocío
          </span>
          <p className="text-[28px] leading-9 font-bold tracking-[-0.02em] text-balance sm:text-[36px] sm:leading-[44px]">
            Plan de riego diario
          </p>
          <p className="hidden text-[15px] leading-6 text-green-50/90 sm:block">
            Cronogramas generados con el modelo, revisados por el encargado y confirmados en campo.
          </p>
          <ul className="mt-3 hidden flex-col gap-2.5 lg:flex">
            {PUNTOS.map(({ icono: Icono, texto }) => (
              <li key={texto} className="flex items-center gap-3 text-sm text-green-50">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/12 ring-1 ring-white/20 ring-inset" aria-hidden="true">
                  <Icono className="size-4" />
                </span>
                {texto}
              </li>
            ))}
          </ul>
        </div>
      </aside>
      <main className="flex items-start justify-center bg-[radial-gradient(700px_400px_at_100%_0%,rgb(163_217_119/0.12),transparent_60%)] px-4 py-8 sm:items-center sm:px-8 lg:py-12">
        <div className="entrada-suave flex w-full max-w-[400px] flex-col gap-6">
          <div className="flex flex-col gap-1.5">
            <h1 className="text-2xl leading-8 font-bold tracking-[-0.02em] text-texto">{titulo}</h1>
            {descripcion && <p className="text-sm text-texto-2">{descripcion}</p>}
          </div>
          {children}
          <p className="text-xs text-texto-3">Plan de Riego · Grupo El Rocío</p>
        </div>
      </main>
    </div>
  );
}
