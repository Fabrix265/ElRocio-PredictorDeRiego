import { useQuery } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router";

import { leerPreferencia, guardarPreferencia } from "../../lib/preferencias";
import { useAuth } from "../auth/AuthProvider";
import { catalogoApi, claveCatalogo, type Fundo, type Modulo } from "./api";

/**
 * Fundo y módulo seleccionados en la cabecera. Se eligen por código (estable entre bases):
 * primero `?modulo=` de la URL (enlaces de correo), luego la última elección guardada y, si no,
 * el primer módulo del catálogo. Al cambiar, se guarda y se refleja en la URL.
 */
interface ValorSeleccion {
  fundos: Fundo[];
  fundo: Fundo | null;
  modulo: Modulo | null;
  cargando: boolean;
  error: boolean;
  seleccionarFundo: (codigo: string) => void;
  seleccionarModulo: (codigo: string) => void;
}

const SeleccionContext = createContext<ValorSeleccion | null>(null);
const CLAVE_MODULO = "modulo";

export function resolverSeleccion(fundos: Fundo[], codigoModulo: string | null, codigoFundo: string | null) {
  const conModulo = codigoModulo
    ? fundos.find((f) => f.modulos.some((m) => m.codigo === codigoModulo))
    : undefined;
  const fundo = conModulo ?? fundos.find((f) => f.codigo === codigoFundo) ?? fundos[0] ?? null;
  const modulo = fundo?.modulos.find((m) => m.codigo === codigoModulo) ?? fundo?.modulos[0] ?? null;
  return { fundo, modulo };
}

export function SeleccionProvider({ children }: { children: ReactNode }) {
  const { usuario } = useAuth();
  const [params, setParams] = useSearchParams();
  const [elegido, setElegido] = useState<{ fundo: string | null; modulo: string | null }>(() => ({
    fundo: leerPreferencia("fundo"),
    modulo: leerPreferencia("modulo"),
  }));

  const consulta = useQuery({
    queryKey: claveCatalogo.fundos,
    queryFn: ({ signal }) => catalogoApi.fundos(signal),
    enabled: !!usuario && !usuario.debe_cambiar_password,
    staleTime: 10 * 60 * 1000,
  });

  const fundos = useMemo(() => consulta.data ?? [], [consulta.data]);
  const moduloUrl = params.get(CLAVE_MODULO);
  const { fundo, modulo } = useMemo(
    () => resolverSeleccion(fundos, moduloUrl ?? elegido.modulo, elegido.fundo),
    [fundos, moduloUrl, elegido],
  );

  // Un `?modulo=` válido que llega por la URL pasa a ser la elección guardada.
  useEffect(() => {
    if (!moduloUrl || !fundo || !modulo || modulo.codigo !== moduloUrl) return;
    if (elegido.modulo === moduloUrl && elegido.fundo === fundo.codigo) return;
    setElegido({ fundo: fundo.codigo, modulo: moduloUrl });
    guardarPreferencia("fundo", fundo.codigo);
    guardarPreferencia("modulo", moduloUrl);
  }, [moduloUrl, fundo, modulo, elegido]);

  const aplicar = useCallback(
    (codigoFundo: string, codigoModulo: string | null) => {
      setElegido({ fundo: codigoFundo, modulo: codigoModulo });
      guardarPreferencia("fundo", codigoFundo);
      guardarPreferencia("modulo", codigoModulo);
      setParams(
        (actual) => {
          const nuevos = new URLSearchParams(actual);
          if (codigoModulo) nuevos.set(CLAVE_MODULO, codigoModulo);
          else nuevos.delete(CLAVE_MODULO);
          return nuevos;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const seleccionarFundo = useCallback(
    (codigo: string) => {
      const f = fundos.find((x) => x.codigo === codigo);
      if (f) aplicar(f.codigo, f.modulos[0]?.codigo ?? null);
    },
    [fundos, aplicar],
  );

  const seleccionarModulo = useCallback(
    (codigo: string) => {
      const f = fundos.find((x) => x.modulos.some((m) => m.codigo === codigo));
      if (f) aplicar(f.codigo, codigo);
    },
    [fundos, aplicar],
  );

  const valor = useMemo<ValorSeleccion>(
    () => ({
      fundos,
      fundo,
      modulo,
      cargando: consulta.isPending && consulta.fetchStatus !== "idle",
      error: consulta.isError,
      seleccionarFundo,
      seleccionarModulo,
    }),
    [fundos, fundo, modulo, consulta.isPending, consulta.fetchStatus, consulta.isError, seleccionarFundo, seleccionarModulo],
  );

  return <SeleccionContext.Provider value={valor}>{children}</SeleccionContext.Provider>;
}

export function useSeleccion(): ValorSeleccion {
  const ctx = useContext(SeleccionContext);
  if (!ctx) throw new Error("useSeleccion debe usarse dentro de SeleccionProvider");
  return ctx;
}
