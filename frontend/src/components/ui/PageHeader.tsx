import type { ReactNode } from "react";

interface PageHeaderProps {
  /** Texto pequeño en mayúsculas sobre el título (sección). */
  antetitulo?: ReactNode;
  titulo: ReactNode;
  descripcion?: ReactNode;
  acciones?: ReactNode;
}

export function PageHeader({ antetitulo, titulo, descripcion, acciones }: PageHeaderProps) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-1.5">
        {antetitulo && (
          <span className="inline-flex items-center gap-2 text-[11px] font-semibold tracking-[0.1em] text-green-600 uppercase">
            <span className="h-[3px] w-4 rounded-full bg-linear-to-r from-green-500 to-lima" aria-hidden="true" />
            {antetitulo}
          </span>
        )}
        <h1 className="text-[22px] leading-7 font-bold tracking-[-0.02em] text-texto sm:text-2xl sm:leading-8">{titulo}</h1>
        {descripcion && <p className="max-w-[68ch] text-[13px] leading-5 text-texto-2">{descripcion}</p>}
      </div>
      {acciones && <div className="flex flex-wrap items-center gap-2">{acciones}</div>}
    </div>
  );
}
