import { Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "../../lib/cn";

export type VarianteBoton = "primario" | "secundario" | "fantasma" | "peligro" | "peligroSuave";
export type TamanoBoton = "sm" | "md" | "lg" | "icono";

const BASE =
  "inline-flex items-center justify-center gap-2 rounded-md border font-medium whitespace-nowrap select-none " +
  "transition-[background,color,border-color,box-shadow,transform] duration-150 active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-foco " +
  "focus-visible:shadow-[0_0_0_4px_var(--foco-anillo)] disabled:cursor-not-allowed [&_svg]:size-4 [&_svg]:shrink-0";

const VARIANTES: Record<VarianteBoton, string> = {
  primario:
    "bg-marca bg-[image:var(--degradado-boton)] text-marca-texto border-transparent shadow-marca " +
    "hover:bg-[image:var(--degradado-boton-hover)] active:bg-green-800 " +
    "disabled:bg-sand-300 disabled:bg-none disabled:text-white disabled:shadow-none",
  secundario:
    "bg-superficie text-texto border-borde shadow-[0_1px_2px_rgb(18_48_31/0.05)] hover:bg-activo-bg hover:text-activo-tx hover:border-green-400 " +
    "disabled:bg-deshabilitado disabled:text-texto-3 disabled:border-borde",
  fantasma:
    "bg-transparent text-activo-tx border-transparent hover:bg-activo-bg disabled:text-texto-3 disabled:bg-transparent",
  /** Acción destructiva secundaria (p. ej. «Eliminar» junto a «Publicar»): borde y texto rojos. */
  peligroSuave:
    "bg-superficie text-err-tx border-err/25 hover:bg-err-bg hover:border-err/45 " +
    "disabled:bg-deshabilitado disabled:text-texto-3 disabled:border-borde",
  peligro:
    "bg-err text-white border-transparent shadow-[0_1px_2px_rgb(120_20_15/0.25)] hover:bg-err-tx " +
    "disabled:bg-sand-300 disabled:text-white disabled:shadow-none",
};

const TAMANOS: Record<TamanoBoton, string> = {
  sm: "h-8 px-3 text-[13px]",
  md: "h-9 px-4 text-[13.5px]",
  lg: "h-11 px-5 text-sm",
  icono: "size-9 p-0",
};

/** Clases de botón para aplicar también a enlaces (`<Link>`). */
export function clasesBoton(variante: VarianteBoton = "primario", tamano: TamanoBoton = "md", extra?: string) {
  return cn(BASE, VARIANTES[variante], TAMANOS[tamano], extra);
}

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variante?: VarianteBoton;
  tamano?: TamanoBoton;
  cargando?: boolean;
  icono?: ReactNode;
}

export function Button({
  variante = "primario",
  tamano = "md",
  cargando = false,
  icono,
  disabled,
  className,
  children,
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={clasesBoton(variante, tamano, className)}
      disabled={disabled || cargando}
      aria-busy={cargando || undefined}
      {...props}
    >
      {cargando ? <Loader2 className="animate-spin" aria-hidden="true" /> : icono}
      {children}
    </button>
  );
}
