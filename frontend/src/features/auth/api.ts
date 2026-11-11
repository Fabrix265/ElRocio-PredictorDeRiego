import { api, solicitar } from "../../services/httpClient";
import type { RespuestaSesion, Usuario } from "../../services/tipos";

export const authApi = {
  login: (username: string, password: string) =>
    solicitar<RespuestaSesion>("/auth/login", {
      method: "POST",
      body: { username, password },
      autenticado: false,
    }),
  logout: () => solicitar<void>("/auth/logout", { method: "POST", sinReintento: true }),
  me: () => api.get<Usuario>("/auth/me"),
  recuperar: (identificador: string) =>
    solicitar<{ detail: string }>("/auth/recuperar", {
      method: "POST",
      body: { identificador },
      autenticado: false,
    }),
  restablecer: (token: string, password: string) =>
    solicitar<void>("/auth/restablecer", {
      method: "POST",
      body: { token, password },
      autenticado: false,
    }),
  cambiarPassword: (password_actual: string, password_nueva: string) =>
    api.post<RespuestaSesion>("/auth/cambiar-password", { password_actual, password_nueva }),
};
