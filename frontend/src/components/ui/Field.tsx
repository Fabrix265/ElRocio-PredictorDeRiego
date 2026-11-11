import { AlertCircle } from "lucide-react";
import { cloneElement, isValidElement, useId, type ReactElement, type ReactNode } from "react";

import { cn } from "../../lib/cn";

interface FieldProps {
  label: ReactNode;
  /** Mensaje de error del campo (se anuncia y se enlaza con aria-describedby). */
  error?: string;
  ayuda?: ReactNode;
  requerido?: boolean;
  className?: string;
  /** Un único control (Input, PasswordInput, Select…); recibe id y atributos ARIA. */
  children: ReactElement<Record<string, unknown>>;
}

export function Field({ label, error, ayuda, requerido, className, children }: FieldProps) {
  const id = useId();
  const idControl = (children.props.id as string | undefined) ?? `campo-${id.replace(/:/g, "")}`;
  const idAyuda = ayuda ? `${idControl}-ayuda` : undefined;
  const idError = error ? `${idControl}-error` : undefined;
  const describedBy = [idAyuda, idError].filter(Boolean).join(" ") || undefined;

  const control = isValidElement(children)
    ? cloneElement(children, {
        id: idControl,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": describedBy,
        "aria-required": requerido || undefined,
      })
    : children;

  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <label htmlFor={idControl} className="text-[13px] font-medium text-texto">
        {label}
        {requerido && (
          <span className="ml-0.5 text-err-tx" aria-hidden="true">
            *
          </span>
        )}
      </label>
      {control}
      {ayuda && (
        <p id={idAyuda} className="text-xs text-texto-2">
          {ayuda}
        </p>
      )}
      {error && (
        <p id={idError} className="flex items-start gap-1.5 text-xs font-medium text-err-tx">
          <AlertCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
          {error}
        </p>
      )}
    </div>
  );
}
