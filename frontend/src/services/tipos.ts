import type { Rol } from "../lib/roles";

/** Usuario tal como lo devuelve el backend (`usuario` del contrato HTTP). */
export interface Usuario {
  id: number;
  username: string;
  nombre: string;
  correo: string;
  rol: Rol;
  activo: boolean;
  debe_cambiar_password: boolean;
  ultimo_acceso_at: string | null;
}

/** Cuerpo de login, refresh y cambiar-password. */
export interface RespuestaSesion {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  usuario: Usuario;
}

/** Error de validación de FastAPI (422). */
export interface ErrorValidacion {
  loc: Array<string | number>;
  msg: string;
  type?: string;
}
