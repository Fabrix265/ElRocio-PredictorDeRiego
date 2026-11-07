import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { forwardRef } from "react";

import { cn } from "../../lib/cn";

export interface OpcionSelect {
  value: string;
  label: string;
}

interface SelectProps {
  value: string;
  onValueChange: (valor: string) => void;
  opciones: OpcionSelect[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  id?: string;
  name?: string;
  "aria-label"?: string;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
  "aria-required"?: boolean;
}

/** Select accesible (Radix). Los valores no pueden ser cadena vacía: usa p. ej. "todos". */
export const Select = forwardRef<HTMLButtonElement, SelectProps>(function Select(
  { value, onValueChange, opciones, placeholder = "Selecciona…", disabled, className, name, ...aria },
  ref,
) {
  return (
    <SelectPrimitive.Root value={value || undefined} onValueChange={onValueChange} disabled={disabled} name={name}>
      <SelectPrimitive.Trigger
        ref={ref}
        className={cn(
          "inline-flex h-10 w-full min-w-0 items-center justify-between gap-2 rounded-md border border-borde-input bg-superficie px-3 text-left text-sm text-texto",
          "hover:border-sand-600 focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-foco focus-visible:shadow-[0_0_0_4px_var(--foco-anillo)]",
          "disabled:cursor-not-allowed disabled:bg-deshabilitado disabled:text-texto-3 data-[placeholder]:text-texto-3",
          "aria-[invalid=true]:border-err",
          className,
        )}
        {...aria}
      >
        <span className="truncate">
          <SelectPrimitive.Value placeholder={placeholder} />
        </span>
        <SelectPrimitive.Icon>
          <ChevronDown className="size-4 text-texto-2" aria-hidden="true" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={4}
          className="z-50 max-h-[min(var(--radix-select-content-available-height),320px)] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg border border-borde bg-superficie shadow-elevada"
        >
          <SelectPrimitive.Viewport className="p-1">
            {opciones.map((op) => (
              <SelectPrimitive.Item
                key={op.value}
                value={op.value}
                className="relative flex h-9 cursor-pointer items-center rounded-md pr-8 pl-3 text-sm text-texto outline-none select-none data-[highlighted]:bg-activo-bg data-[highlighted]:text-activo-tx data-[state=checked]:font-semibold"
              >
                <SelectPrimitive.ItemText>{op.label}</SelectPrimitive.ItemText>
                <SelectPrimitive.ItemIndicator className="absolute right-2 inline-flex">
                  <Check className="size-4 text-marca" aria-hidden="true" />
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
});
