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
    <time dateTime={hoyLima(ahora)} className="hidden text-[13px] whitespace-nowrap text-texto-2 sm:inline">
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
    <header className="sticky top-0 z-30 flex h-[var(--cabecera-alto)] shrink-0 items-center gap-3 border-b-[3px] border-marca bg-superficie px-3 sm:px-5">
      <div className="min-w-0 flex-1">
        <SelectorFundo />
      </div>
      <FechaHoy />
      <MenuUsuario />
    </header>
  );
}
