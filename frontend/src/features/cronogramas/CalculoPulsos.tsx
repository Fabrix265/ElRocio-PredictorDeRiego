import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { cn } from "../../lib/cn";
import type { CalculoPulsos as Calculo } from "../../services/cronogramas";
import { formato } from "./etiquetas";

const TH = "border-b border-borde bg-hundido px-2.5 py-2 text-left text-xs font-semibold text-texto-2";
const TD = "border-b border-borde px-2.5 py-1.5 whitespace-nowrap tabular-nums";

const pct = (x: number) => `${(x * 100).toLocaleString("es-PE", { maximumFractionDigits: 2 })} %`;
const num = (x: number, d = 1) => x.toLocaleString("es-PE", { minimumFractionDigits: d, maximumFractionDigits: d });

/** Cómo se repartieron los m³/ha del modelo en pulsos (la lógica de la planilla de riego por pulsos). */
export function CalculoPulsos({ calculo }: { calculo: Calculo }) {
  const d = calculo.derivados;
  const bloques = calculo.bloques.map((b, i) => ({ ...b, i })).filter((b) => b.horas > 0 || b.minutos_riego > 0);
  return (
    <section aria-labelledby="titulo-pulsos" className="flex flex-col gap-3 border-t border-borde px-4 pt-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id="titulo-pulsos" className="text-sm font-semibold text-texto">Cálculo por pulsos</h3>
        <Badge tono="marca">Curva {calculo.curva}{calculo.ventana ? ` · ${calculo.ventana[0]}–${calculo.ventana[1]}` : ""}</Badge>
        <Badge tono={calculo.converge ? "exito" : "error"}>{calculo.converge ? "Todos convergen" : "No converge"}</Badge>
      </div>
      <p className="text-sm text-texto-2">
        El modelo da los m³/ha de cada turno; la planilla los reparte en pulsos. {calculo.motivo}.
      </p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-texto-2 sm:grid-cols-4">
        <div><dt>Fase</dt><dd className="font-semibold text-texto">{calculo.fase_fenologica}</dd></div>
        <div><dt>Agotamiento por pulso</dt><dd className="font-semibold text-texto">{pct(d.agotamiento_operativo)}</dd></div>
        <div><dt>Pulso base</dt><dd className="font-semibold text-texto">{num(d.volumen_pulso_m3ha, 2)} m³/ha · {num(d.minutos_pulso)} min</dd></div>
        <div><dt>Capacidad de riego</dt><dd className="font-semibold text-texto">{num(d.capacidad_riego_m3hah, 2)} m³/ha/h</dd></div>
        <div><dt>Agua disponible</dt><dd className="text-texto">{num(d.agua_disponible_m3ha, 1)} m³/ha</dd></div>
        <div><dt>ETr equivalente</dt><dd className="text-texto">{num(calculo.etr_equivalente_mm, 2)} mm</dd></div>
        <div><dt>Curva por umbral</dt><dd className="text-texto">{calculo.curva_propuesta}</dd></div>
        <div><dt>Volumen del pulso</dt><dd className="text-texto">{calculo.reglas.ajustar_pulso_al_total ? "Ajustado al total del modelo" : "Fijo"}</dd></div>
      </dl>
      {calculo.avisos.map((a) => <Alert key={a} tono="aviso">{a}</Alert>)}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-sm">
          <caption className="sr-only">Pulsos por turno y bloque de 3 horas</caption>
          <thead>
            <tr>
              <th className={TH}>Turno</th>
              <th className={cn(TH, "text-right")}>Modelo m³/ha</th>
              {bloques.map((b) => <th key={b.i} className={cn(TH, "text-center")}>{b.inicio}</th>)}
              <th className={cn(TH, "text-right")}>Ciclos</th>
              <th className={cn(TH, "text-right")}>m³/ha c/u</th>
            </tr>
          </thead>
          <tbody>
            {calculo.turnos.map((t) => (
              <tr key={t.turno}>
                <td className={cn(TD, "font-semibold text-texto")}>{t.turno}</td>
                <td className={cn(TD, "text-right")}>{formato.m3ha(t.m3ha_modelo)}</td>
                {bloques.map((b) => (
                  <td key={b.i} className={cn(TD, "text-center")} title={`Teóricos: ${num(t.pulsos_teoricos[b.i], 2)}`}>
                    {t.pulsos_por_bloque[b.i] || "—"}
                  </td>
                ))}
                <td className={cn(TD, "text-right font-semibold")}>{t.n_ciclos}</td>
                <td className={cn(TD, "text-right")}>{formato.m3ha(t.m3ha_pulso)}</td>
              </tr>
            ))}
            <tr className="text-xs text-texto-2">
              <td className={TD} colSpan={2}>Riego / útil (min)</td>
              {bloques.map((b) => (
                <td key={b.i} className={cn(TD, "text-center", !b.converge && "font-semibold text-err-tx")}>
                  {num(b.minutos_riego, 0)}/{num(b.minutos_utiles, 0)}
                </td>
              ))}
              <td className={TD} colSpan={2} />
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
