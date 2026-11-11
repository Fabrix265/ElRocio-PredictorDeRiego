import { forwardRef, useEffect, useImperativeHandle, useRef, type InputHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "checked"> {
  /** true, false o "mixto" (algunos marcados: se muestra indeterminado). */
  checked: boolean | "mixto";
}

/** Casilla nativa (accesible y con teclado) con el verde de marca; admite estado mixto. */
export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { checked, className, ...props },
  ref,
) {
  const interno = useRef<HTMLInputElement>(null);
  useImperativeHandle(ref, () => interno.current as HTMLInputElement);
  useEffect(() => {
    if (interno.current) interno.current.indeterminate = checked === "mixto";
  }, [checked]);
  return (
    <input
      ref={interno}
      type="checkbox"
      checked={checked === true}
      aria-checked={checked === "mixto" ? "mixed" : checked}
      className={cn(
        "size-4 shrink-0 cursor-pointer rounded-sm accent-marca disabled:cursor-not-allowed disabled:opacity-50",
        "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-foco",
        className,
      )}
      {...props}
    />
  );
});
