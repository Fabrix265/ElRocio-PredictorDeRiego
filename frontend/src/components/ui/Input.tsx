import { forwardRef, type InputHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export const clasesInput =
  "h-10 w-full min-w-0 rounded-md border border-borde-input bg-superficie px-3 text-sm text-texto " +
  "transition-colors hover:border-sand-600 focus-visible:outline-2 focus-visible:outline-offset-0 " +
  "focus-visible:outline-foco focus-visible:shadow-[0_0_0_4px_var(--foco-anillo)] " +
  "disabled:cursor-not-allowed disabled:bg-deshabilitado disabled:text-texto-3 " +
  "aria-[invalid=true]:border-err aria-[invalid=true]:hover:border-err";

export type InputProps = InputHTMLAttributes<HTMLInputElement>;

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ className, ...props }, ref) {
  return <input ref={ref} className={cn(clasesInput, className)} {...props} />;
});
