/**
 * Reportes y datos de campo (F5).
 *
 * Contrato del backend (prefijo /api/v1; esquemas en backend/app/schemas/reportes.py y datos.py):
 * - GET /dashboard?modulo_id                         → DashboardSalida (P: sin aplicado vs modelo)
 * - GET /datos/agua?modulo_id&desde&hasta            → AguaSalida (P: sin modelo_*)
 * - GET /datos/clima|suelo|planta?desde&hasta        → SerieSalida (diaria; por defecto 14 días hasta ayer)
 * - GET /datos/pronostico?desde&hasta                → SerieSalida (última captura)
 * - GET /cronogramas/{id}/exportar?formato=pdf|xlsx&orden=turno|hora → archivo (auditado)
 * - GET /exportaciones/refinamiento.csv?desde&hasta  → CSV (solo admin)
 */
import { api, descargar } from "./httpClient";

export type OrdenPlan = "turno" | "hora";

export interface Serie {
  fuente: string;
  resolucion: string;
  desde: string | null;
  hasta: string | null;
  capturado_fecha: string | null;
  unidades: Record<string, string>;
  puntos: Array<Record<string, number | string | boolean | null> & { fecha?: string }>;
}

export interface AguaTurno {
  turno_id: number;
  turno_codigo: string;
  area_ha: number;
  aplicado_m3ha: number | null;
  aplicado_m3: number | null;
  estado_riego: "aplicado" | "provisional" | null;
  sin_riego: boolean;
  propuesto_m3ha: number | null;
  propuesto_m3: number | null;
  modelo_m3ha: number | null;
  modelo_m3: number | null;
}

export interface AguaDia {
  fecha: string;
  cronograma_id: number | null;
  turnos: AguaTurno[];
}

export interface Agua {
  modulo_id: number;
  desde: string;
  hasta: string;
  con_modelo: boolean;
  dias: AguaDia[];
}

export interface Dashboard {
  modulo_id: number;
  fecha: string;
  ayer: string;
  agua_aplicada_m3ha: number | null;
  agua_aplicada_m3: number | null;
  turnos_con_riego: number;
  ultimo_riego_fecha: string | null;
  turnos_total: number;
  aplicado_vs_modelo_pct: number | null;
  mds_um: number | null;
  eto_mm: number | null;
  estado_manana: string | null;
  cronograma_manana_id: number | null;
  pronostico: Serie;
}

export const claveReportes = {
  todo: ["reportes"] as const,
  dashboard: (moduloId: number) => ["reportes", "dashboard", moduloId] as const,
  agua: (moduloId: number, desde: string, hasta: string) => ["reportes", "agua", moduloId, desde, hasta] as const,
  serie: (fuente: string, desde: string, hasta: string, moduloId: number) => ["reportes", "serie", fuente, desde, hasta, moduloId] as const,
};

export const reportesApi = {
  dashboard(moduloId: number, signal?: AbortSignal): Promise<Dashboard> {
    return api.get<Dashboard>("/dashboard", { modulo_id: moduloId }, signal);
  },
  agua(moduloId: number, desde: string, hasta: string, signal?: AbortSignal): Promise<Agua> {
    return api.get<Agua>("/datos/agua", { modulo_id: moduloId, desde, hasta }, signal);
  },
  serie(fuente: "clima" | "suelo" | "planta", desde: string, hasta: string, moduloId: number, signal?: AbortSignal): Promise<Serie> {
    const query = fuente === "planta" ? { desde, hasta } : { desde, hasta, modulo_id: moduloId };
    return api.get<Serie>(`/datos/${fuente}`, query, signal);
  },
  pronostico(desde: string, hasta: string, signal?: AbortSignal): Promise<Serie> {
    return api.get<Serie>("/datos/pronostico", { desde, hasta }, signal);
  },
  exportarCronograma(id: number, formato: "pdf" | "xlsx", orden: OrdenPlan = "turno"): Promise<string> {
    return descargar(`/cronogramas/${id}/exportar`, { formato, orden }, `cronograma.${formato}`);
  },
  refinamiento(desde: string, hasta: string): Promise<string> {
    return descargar("/exportaciones/refinamiento.csv", { desde, hasta }, "refinamiento.csv");
  },
};
