import { z } from "zod";

import { erroresPassword } from "../../lib/password";

const requerido = (mensaje: string) => z.string().trim().min(1, mensaje);

export const esquemaLogin = z.object({
  username: requerido("Ingresa tu usuario."),
  password: z.string().min(1, "Ingresa tu contraseña."),
});
export type DatosLogin = z.infer<typeof esquemaLogin>;

export const esquemaRecuperar = z.object({
  identificador: requerido("Ingresa tu usuario o correo."),
});
export type DatosRecuperar = z.infer<typeof esquemaRecuperar>;

/** Agrega al contexto de zod el primer error de la política de contraseña. */
export function validarPoliticaEn(
  ctx: z.RefinementCtx,
  campo: string,
  password: string,
  username?: string | null,
): void {
  const [primero] = erroresPassword(password, username);
  if (primero) ctx.addIssue({ code: "custom", path: [campo], message: primero });
}

export const esquemaRestablecer = z
  .object({
    password: z.string().min(1, "Ingresa la nueva contraseña."),
    confirmar: z.string().min(1, "Repite la nueva contraseña."),
  })
  .superRefine((d, ctx) => {
    validarPoliticaEn(ctx, "password", d.password);
    if (d.confirmar && d.password !== d.confirmar) {
      ctx.addIssue({ code: "custom", path: ["confirmar"], message: "Las contraseñas no coinciden." });
    }
  });
export type DatosRestablecer = z.infer<typeof esquemaRestablecer>;

export function crearEsquemaCambio(username: string) {
  return z
    .object({
      actual: z.string().min(1, "Ingresa tu contraseña actual."),
      nueva: z.string().min(1, "Ingresa la nueva contraseña."),
      confirmar: z.string().min(1, "Repite la nueva contraseña."),
    })
    .superRefine((d, ctx) => {
      validarPoliticaEn(ctx, "nueva", d.nueva, username);
      if (d.nueva && d.actual && d.nueva === d.actual) {
        ctx.addIssue({ code: "custom", path: ["nueva"], message: "Debe ser distinta de la contraseña actual." });
      }
      if (d.confirmar && d.nueva !== d.confirmar) {
        ctx.addIssue({ code: "custom", path: ["confirmar"], message: "Las contraseñas no coinciden." });
      }
    });
}
export type DatosCambio = z.infer<ReturnType<typeof crearEsquemaCambio>>;
