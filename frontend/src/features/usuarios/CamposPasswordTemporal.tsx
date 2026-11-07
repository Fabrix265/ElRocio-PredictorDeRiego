import { Wand2 } from "lucide-react";
import type { UseFormRegisterReturn } from "react-hook-form";

import { Button } from "../../components/ui/Button";
import { Field } from "../../components/ui/Field";
import { PasswordInput } from "../../components/ui/PasswordInput";
import { ReglasPassword } from "../auth/ReglasPassword";

interface Props {
  registroPassword: UseFormRegisterReturn;
  registroConfirmar: UseFormRegisterReturn;
  errorPassword?: string;
  errorConfirmar?: string;
  valor: string;
  username?: string;
  alGenerar: () => void;
}

/** Contraseña temporal + confirmación, con generador y reglas en vivo. */
export function CamposPasswordTemporal({
  registroPassword,
  registroConfirmar,
  errorPassword,
  errorConfirmar,
  valor,
  username,
  alGenerar,
}: Props) {
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-borde bg-fondo p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] font-medium text-texto">Contraseña temporal</p>
        <Button variante="fantasma" tamano="sm" icono={<Wand2 aria-hidden="true" />} onClick={alGenerar}>
          Generar una segura
        </Button>
      </div>
      <Field label="Contraseña temporal" error={errorPassword} requerido>
        <PasswordInput autoComplete="new-password" {...registroPassword} />
      </Field>
      <ReglasPassword password={valor} username={username} />
      <Field label="Repite la contraseña temporal" error={errorConfirmar} requerido>
        <PasswordInput autoComplete="new-password" {...registroConfirmar} />
      </Field>
      <p className="text-xs text-texto-2">
        Entrégala al usuario por un medio seguro. Deberá cambiarla la primera vez que ingrese.
      </p>
    </div>
  );
}
