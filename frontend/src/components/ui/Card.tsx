import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "../../lib/cn";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("min-w-0 rounded-lg border border-borde bg-superficie shadow-suave", className)} {...props} />;
}

export function CardHeader({
  titulo,
  acciones,
  descripcion,
  className,
}: {
  titulo: ReactNode;
  acciones?: ReactNode;
  descripcion?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-start justify-between gap-2 px-4 pt-3.5", className)}>
      <div className="flex min-w-0 flex-col gap-0.5">
        <h3 className="text-[15px] leading-[22px] font-semibold text-texto">{titulo}</h3>
        {descripcion && <p className="text-xs text-texto-2">{descripcion}</p>}
      </div>
      {acciones && <div className="flex items-center gap-2">{acciones}</div>}
    </div>
  );
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-4 pt-3 pb-4", className)} {...props} />;
}
