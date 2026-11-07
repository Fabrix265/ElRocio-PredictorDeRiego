import { Eye, EyeOff } from "lucide-react";
import { forwardRef, useState } from "react";

import { cn } from "../../lib/cn";
import { Input, type InputProps } from "./Input";

/** Campo de contraseña con botón para mostrar u ocultar el texto. */
export const PasswordInput = forwardRef<HTMLInputElement, Omit<InputProps, "type">>(function PasswordInput(
  { className, ...props },
  ref,
) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input ref={ref} type={visible ? "text" : "password"} className={cn("pr-11", className)} {...props} />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-md text-texto-2 hover:text-activo-tx focus-visible:outline-2 focus-visible:outline-foco"
        aria-label={visible ? "Ocultar contraseña" : "Mostrar contraseña"}
        aria-pressed={visible}
        disabled={props.disabled}
      >
        {visible ? <EyeOff className="size-4" aria-hidden="true" /> : <Eye className="size-4" aria-hidden="true" />}
      </button>
    </div>
  );
});
