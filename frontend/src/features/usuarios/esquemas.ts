import { z } from "zod";

import { ROLES } from "../../lib/roles";
import { validarPoliticaEn } from "../auth/esquemas";

export const PATRON_USERNAME = /^[A-Za-z0-9._-]{3,50}$/;

const nombre = z.string().trim().min(2, "Ingresa el nombre completo.").max(120, "Máximo 120 caracteres.");
const correo = z.string().trim().min(1, "Ingresa el correo.").max(254, "Máximo 254 caracteres.").pipe(z.email("Ingresa un correo válido."));
const rol = z.enum(ROLES, { error: "Elige un rol." });

export const esquemaNuevoUsuario = z
  .object({
    username: z
      .string()
      .trim()
      .regex(PATRON_USERNAME, "De 3 a 50 caracteres: letras sin tilde, números, punto, guion o guion bajo."),
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
