import { z } from "zod";

import { ROLES } from "../../lib/roles";
import { validarPoliticaEn } from "../auth/esquemas";

/**
 * Mismo contrato que el backend (backend/app/schemas/usuarios.py): se recorta, se pasa a
 * minúsculas y debe cumplir ^[a-z0-9._-]{3,60}$ (60 = largo de la columna).
 */
export const USERNAME_MAX = 60;
export const PATRON_USERNAME = /^[a-z0-9._-]{3,60}$/;
export const MENSAJE_USERNAME =
  "El usuario debe tener de 3 a 60 caracteres: letras sin tilde, números, punto, guion o guion bajo.";
export const NOMBRE_MAX = 120;
export const CORREO_MAX = 254;

const nombre = z.string().trim().min(2, "Ingresa el nombre completo.").max(NOMBRE_MAX, `Máximo ${NOMBRE_MAX} caracteres.`);
const correo = z
  .string()
  .trim()
  .min(1, "Ingresa el correo.")
  .max(CORREO_MAX, `Máximo ${CORREO_MAX} caracteres.`)
  .pipe(z.email("Ingresa un correo válido."));
const rol = z.enum(ROLES, { error: "Elige un rol." });

export const esquemaNuevoUsuario = z
  .object({
    username: z.string().trim().toLowerCase().regex(PATRON_USERNAME, MENSAJE_USERNAME),
    nombre,
    correo,
    rol,
    password_temporal: z.string().min(1, "Ingresa una contraseña temporal."),
    confirmar: z.string().min(1, "Repite la contraseña temporal."),
  })
  .superRefine((d, ctx) => {
    validarPoliticaEn(ctx, "password_temporal", d.password_temporal, d.username);
    if (d.confirmar && d.confirmar !== d.password_temporal) {
      ctx.addIssue({ code: "custom", path: ["confirmar"], message: "Las contraseñas no coinciden." });
    }
  });
export type DatosNuevoUsuario = z.infer<typeof esquemaNuevoUsuario>;

export const esquemaEditarUsuario = z.object({ nombre, correo, rol });
export type DatosEditarUsuario = z.infer<typeof esquemaEditarUsuario>;

export function crearEsquemaPasswordTemporal(username: string) {
  return z
    .object({
      password_temporal: z.string().min(1, "Ingresa una contraseña temporal."),
      confirmar: z.string().min(1, "Repite la contraseña temporal."),
    })
    .superRefine((d, ctx) => {
      validarPoliticaEn(ctx, "password_temporal", d.password_temporal, username);
      if (d.confirmar && d.confirmar !== d.password_temporal) {
        ctx.addIssue({ code: "custom", path: ["confirmar"], message: "Las contraseñas no coinciden." });
      }
    });
}
export type DatosPasswordTemporal = z.infer<ReturnType<typeof crearEsquemaPasswordTemporal>>;
