import { useEffect, useState } from "react";

import { formatearFechaLarga } from "../../lib/fechas";
import { MenuUsuario } from "./MenuUsuario";
import { SelectorFundo } from "./SelectorFundo";

/** Fecha de hoy en Lima; se actualiza cada minuto (cambia sola a medianoche). */
function FechaHoy() {
  const [ahora, setAhora] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setAhora(new Date()), 60_000);
    return () => window.clearInterval(id);
  }, []);
  return (
    <span className="hidden text-[13px] whitespace-nowrap text-texto-2 xl:inline">
      {formatearFechaLarga(ahora)} <span className="text-texto-3">(Lima)</span>
    </span>
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
