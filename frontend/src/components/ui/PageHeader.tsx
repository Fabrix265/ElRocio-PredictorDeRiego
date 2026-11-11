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
      <div className="flex min-w-0 flex-col gap-1">
        {antetitulo && (
          <span className="text-xs font-semibold tracking-[0.08em] text-texto-3 uppercase">{antetitulo}</span>
        )}
        <h1 className="text-xl leading-7 font-semibold text-texto">{titulo}</h1>
        {descripcion && <p className="max-w-[68ch] text-[13px] text-texto-2">{descripcion}</p>}
      </div>
      {acciones && <div className="flex flex-wrap items-center gap-2">{acciones}</div>}
    </div>
  );
}
