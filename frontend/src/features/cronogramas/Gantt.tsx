import { cn } from "../../lib/cn";
import type { TurnoCronograma } from "../../services/cronogramas";
import { formato, minutosAHora } from "./etiquetas";

const HORAS = [0, 3, 6, 9, 12, 15, 18, 21, 24];

/**
 * Gantt de ciclos por turno en el día (00:00–24:00; si algún ciclo termina al día siguiente la escala
 * se alarga hasta su fin). Cada barra lleva en el title el ciclo, el horario y el volumen.
 */
export function Gantt({ turnos, compacto = false }: { turnos: TurnoCronograma[]; compacto?: boolean }) {
  const fin = Math.max(1440, ...turnos.flatMap((t) => t.ciclos.map((c) => c.fin_min)));
  const escala = Math.ceil(fin / 180) * 180;
  const pct = (min: number) => `${(min / escala) * 100}%`;
  const marcas = HORAS.filter((h) => h * 60 <= escala).concat(escala > 1440 ? [escala / 60] : []);

  return (
    <div className="flex flex-col gap-1.5" role="img" aria-label="Diagrama de ciclos por turno a lo largo del día">
      {turnos.map((t) => (
        <div key={t.turno_id} className="grid grid-cols-[44px_1fr] items-center gap-2">
          <span className="text-xs font-semibold text-texto-2">{t.turno_codigo}</span>
          <div className={cn("relative rounded-md bg-hundido", compacto ? "h-5" : "h-7")}>
            <div
              className="absolute inset-y-0 border-l border-dashed border-borde"
              style={{ left: pct(1440) }}
              aria-hidden="true"
            />
            {t.ciclos.map((c) => (
              <div
                key={c.ciclo}
                className="absolute inset-y-0.5 rounded bg-marca"
                style={{ left: pct(c.inicio_min), width: `max(4px, ${pct(c.fin_min - c.inicio_min)})` }}
                title={`${t.turno_codigo} · ciclo ${c.ciclo}: ${c.hora_inicio}–${c.hora_fin}${c.fin_dia_siguiente ? " (día siguiente)" : ""} · ${formato.m3ha(c.riego_m3ha)} m³/ha`}
              />
            ))}
          </div>
        </div>
      ))}
      <div className="grid grid-cols-[44px_1fr] gap-2" aria-hidden="true">
        <span />
        <div className="relative h-4 text-[10px] text-texto-3">
          {marcas.map((h) => (
            <span key={h} className="absolute -translate-x-1/2" style={{ left: pct(h * 60) }}>
              {h === 24 ? "24h" : minutosAHora(h * 60).slice(0, 2)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
