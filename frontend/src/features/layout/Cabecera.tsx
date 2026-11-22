import { formatearFechaCorta, formatearFechaLarga, hoyLima } from "../../lib/fechas";
import { useAhora } from "../../lib/useAhora";
import { MenuUsuario } from "./MenuUsuario";
import { SelectorFundo } from "./SelectorFundo";

/**
 * Fecha de hoy en Lima: larga desde 1280 px, corta ("sáb 07/11") desde 640 px. En celular va
 * en el cajón del menú (ver MenuInferior) para no apretar el selector a 360 px.
 */
function FechaHoy() {
  const ahora = useAhora();
  const larga = formatearFechaLarga(ahora);
  return (
    <time dateTime={hoyLima(ahora)} className="hidden rounded-full bg-hundido px-3 py-1 text-[12.5px] whitespace-nowrap text-texto-2 ring-1 ring-borde-suave ring-inset sm:inline">
      <span className="xl:hidden" aria-hidden="true" title={`${larga} (Lima)`}>
        {formatearFechaCorta(ahora)}
      </span>
      <span className="sr-only xl:not-sr-only">
        {larga} <span className="text-texto-3">(Lima)</span>
      </span>
    </time>
  );
}

/** Cabecera blanca con filete verde: selector Fundo › Módulo, fecha de hoy y menú de usuario. */
export function Cabecera() {
  return (
    <header className="vidrio sticky top-0 z-30 flex h-[var(--cabecera-alto)] shrink-0 items-center gap-3 border-b border-borde px-3 sm:px-5 after:pointer-events-none after:absolute after:inset-x-0 after:-bottom-px after:h-[2px] after:bg-linear-to-r after:from-green-600 after:via-green-400 after:to-lima/60">
      <div className="min-w-0 flex-1">
        <SelectorFundo />
      </div>
      <FechaHoy />
      <MenuUsuario />
    </header>
  );
}
