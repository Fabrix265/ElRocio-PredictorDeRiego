import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  difundirCierreSesion,
  fijarAccessToken,
  refrescarSesion,
  registrarOyentesSesion,
} from "../../services/httpClient";
import type { RespuestaSesion, Usuario } from "../../services/tipos";
import type { EstadoSesion } from "./acceso";
import { authApi } from "./api";

interface ValorAuth {
  estado: EstadoSesion;
  usuario: Usuario | null;
  /** true si el usuario cerró sesión a propósito (el login no guarda `next`). */
  salidaVoluntaria: boolean;
  iniciarSesion: (username: string, password: string) => Promise<Usuario>;
  cerrarSesion: () => Promise<void>;
  cambiarPassword: (actual: string, nueva: string) => Promise<Usuario>;
  /** Aplica una sesión recibida del backend (login, refresh, cambio de contraseña). */
  aplicarSesion: (sesion: RespuestaSesion) => void;
}

const AuthContext = createContext<ValorAuth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [estado, setEstado] = useState<EstadoSesion>("cargando");
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [salidaVoluntaria, setSalidaVoluntaria] = useState(false);

  const aplicarSesion = useCallback((sesion: RespuestaSesion) => {
    fijarAccessToken(sesion.access_token);
    setUsuario(sesion.usuario);
    setEstado("autenticado");
    setSalidaVoluntaria(false);
  }, []);

  const olvidarSesion = useCallback(() => {
    fijarAccessToken(null);
    setUsuario(null);
    setEstado("anonimo");
    queryClient.clear();
  }, [queryClient]);

  // Oyentes del cliente HTTP: refresh exitoso y sesión perdida (también desde otra pestaña).
  useEffect(
    () =>
      registrarOyentesSesion({
        alRenovar: (sesion) => {
          setUsuario(sesion.usuario);
          setEstado("autenticado");
        },
        alPerder: olvidarSesion,
      }),
    [olvidarSesion],
  );

  // Al cargar la app: refresh silencioso con la cookie (si existe). Vuelo único, así que el
  // doble montaje de StrictMode no genera dos refresh.
  useEffect(() => {
    let vigente = true;
    refrescarSesion()
      .then((sesion) => {
        if (!vigente) return;
        if (sesion) aplicarSesion(sesion);
        else setEstado("anonimo");
      })
      .catch(() => {
        if (vigente) setEstado("anonimo");
      });
    return () => {
      vigente = false;
    };
  }, [aplicarSesion]);

  const iniciarSesion = useCallback(
    async (username: string, password: string) => {
      const sesion = await authApi.login(username, password);
      queryClient.clear();
      aplicarSesion(sesion);
      return sesion.usuario;
    },
    [aplicarSesion, queryClient],
  );

  const cerrarSesion = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      // Aunque falle la red, la sesión local se cierra igual.
    }
    difundirCierreSesion();
    setSalidaVoluntaria(true);
    olvidarSesion();
  }, [olvidarSesion]);

  const cambiarPassword = useCallback(
    async (actual: string, nueva: string) => {
      const sesion = await authApi.cambiarPassword(actual, nueva);
      aplicarSesion(sesion);
      return sesion.usuario;
    },
    [aplicarSesion],
  );

  const valor = useMemo<ValorAuth>(
    () => ({ estado, usuario, salidaVoluntaria, iniciarSesion, cerrarSesion, cambiarPassword, aplicarSesion }),
    [estado, usuario, salidaVoluntaria, iniciarSesion, cerrarSesion, cambiarPassword, aplicarSesion],
  );

  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>;
}

export function useAuth(): ValorAuth {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth debe usarse dentro de AuthProvider");
  return ctx;
}

/** Usuario autenticado (solo dentro de rutas protegidas). */
export function useUsuario(): Usuario {
  const { usuario } = useAuth();
  if (!usuario) throw new Error("useUsuario requiere una sesión activa");
  return usuario;
}
