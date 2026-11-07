import type { Rol } from "../../lib/roles";
import { api } from "../../services/httpClient";
import type { Usuario } from "../../services/tipos";

export interface FiltrosUsuarios {
  q?: string;
  rol?: Rol;
  activo?: boolean;
}

export interface NuevoUsuario {
  username: string;
  nombre: string;
  correo: string;
  rol: Rol;
  password_temporal: string;
}

export type CambiosUsuario = Partial<Pick<Usuario, "nombre" | "correo" | "rol" | "activo">>;

export const usuariosApi = {
  listar: (filtros: FiltrosUsuarios, signal?: AbortSignal) =>
    api.get<Usuario[]>("/usuarios", { q: filtros.q, rol: filtros.rol, activo: filtros.activo }, signal),
  obtener: (id: number) => api.get<Usuario>(`/usuarios/${id}`),
  crear: (datos: NuevoUsuario) => api.post<Usuario>("/usuarios", datos),
  editar: (id: number, cambios: CambiosUsuario) => api.patch<Usuario>(`/usuarios/${id}`, cambios),
  asignarPasswordTemporal: (id: number, password_temporal: string) =>
    api.post<unknown>(`/usuarios/${id}/password-temporal`, { password_temporal }),
};

export const claveUsuarios = {
  todos: ["usuarios"] as const,
  lista: (filtros: FiltrosUsuarios) => ["usuarios", "lista", filtros] as const,
};
