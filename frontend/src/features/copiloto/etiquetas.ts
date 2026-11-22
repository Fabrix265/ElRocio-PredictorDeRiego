import type { TonoBadge } from "../../components/ui/Badge";
import type { EstadoSugerencia, Severidad, TipoSugerencia } from "../../services/copiloto";

export const ETIQUETA_SEVERIDAD: Record<Severidad, string> = { alta: "Alta", media: "Media", info: "Aviso" };
export const TONO_SEVERIDAD: Record<Severidad, TonoBadge> = { alta: "error", media: "aviso", info: "info" };

export const ETIQUETA_TIPO: Record<TipoSugerencia, string> = {
  revisar_equipo: "Revisar equipo",
  revisar_datos: "Revisar datos",
  regenerar_plan: "Regenerar plan",
  ajustar_riego: "Ajustar riego",
  otro: "Otro",
};

export const ETIQUETA_ESTADO_SUGERENCIA: Record<EstadoSugerencia, string> = {
  pendiente: "Pendiente",
  aprobada: "Aprobada",
  descartada: "Descartada",
};
export const TONO_ESTADO_SUGERENCIA: Record<EstadoSugerencia, TonoBadge> = {
  pendiente: "aviso",
  aprobada: "exito",
  descartada: "neutro",
};

const ORDEN: Record<Severidad, number> = { alta: 0, media: 1, info: 2 };

export function ordenarPorSeveridad<T extends { severidad: Severidad }>(alertas: T[]): T[] {
  return [...alertas].sort((a, b) => ORDEN[a.severidad] - ORDEN[b.severidad]);
}

/** «Agente n8n-copiloto» a partir de «agente:n8n-copiloto». */
export function nombreAgente(propuestaPor: string): string {
  return propuestaPor.startsWith("agente:") ? `Agente ${propuestaPor.slice("agente:".length)}` : propuestaPor;
}
