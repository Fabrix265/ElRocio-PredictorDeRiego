import { useCallback, useState, type ReactNode } from "react";
import { Outlet } from "react-router";

import { guardarPreferencia, leerPreferencia } from "../../lib/preferencias";
import { Cabecera } from "./Cabecera";
import { MenuInferior } from "./MenuInferior";
import { Sidebar } from "./Sidebar";

/**
 * Estructura de la app autenticada: barra lateral blanca (escritorio), cabecera con filete verde
 * y menú inferior en celular. Renderiza `children` o, si no hay, la ruta hija.
 */
export function AppLayout({ children }: { children?: ReactNode }) {
  const [colapsada, setColapsada] = useState(() => leerPreferencia("sidebar-colapsada") === "1");
  const alternar = useCallback(() => {
    const nueva = !colapsada;
    guardarPreferencia("sidebar-colapsada", nueva ? "1" : "0");
    setColapsada(nueva);
  }, [colapsada]);

  return (
    <div className="flex min-h-dvh">
      <a
        href="#contenido"
        className="sr-only z-50 rounded-md bg-marca px-3 py-2 text-white focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Saltar al contenido
      </a>
      <Sidebar colapsada={colapsada} alternar={alternar} />
      <div className="flex min-w-0 flex-1 flex-col">
        <Cabecera />
        <main id="contenido" tabIndex={-1} className="flex-1 px-4 pt-4 pb-24 focus:outline-none sm:px-5 sm:pt-5 md:pb-8">
          <div className="mx-auto w-full max-w-[1400px]">{children ?? <Outlet />}</div>
        </main>
      </div>
      <MenuInferior />
    </div>
  );
}
