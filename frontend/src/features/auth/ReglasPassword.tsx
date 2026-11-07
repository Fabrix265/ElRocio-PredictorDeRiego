import { Check, Circle } from "lucide-react";

import { cn } from "../../lib/cn";
import { PASSWORD_MIN } from "../../lib/password";

/** Lista en vivo de la política de contraseña (ícono + texto en cada regla). */
export function ReglasPassword({ password, username }: { password: string; username?: string | null }) {
  const usuario = username?.trim().toLowerCase();
  const reglas = [
    { ok: password.length >= PASSWORD_MIN, texto: `Al menos ${PASSWORD_MIN} caracteres` },
    { ok: /\p{L}/u.test(password), texto: "Incluye letras" },
    { ok: /\p{Nd}/u.test(password), texto: "Incluye números" },
    ...(usuario
      ? [{ ok: password.length > 0 && password.trim().toLowerCase() !== usuario, texto: "Distinta del usuario" }]
      : []),
  ];
  return (
    <ul className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-2" aria-label="Requisitos de la contraseña">
      {reglas.map((r) => (
        <li key={r.texto} className={cn("flex items-center gap-1.5", r.ok ? "text-ok-tx" : "text-texto-2")}>
          {r.ok ? (
            <Check className="size-3.5 shrink-0" aria-hidden="true" />
          ) : (
            <Circle className="size-3 shrink-0" aria-hidden="true" />
          )}
          <span>
            {r.texto}
            <span className="sr-only">{r.ok ? ": cumple" : ": pendiente"}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
