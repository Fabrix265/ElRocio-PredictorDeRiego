import type { Rol } from "../../lib/roles";
import { api } from "../../services/httpClient";

export interface RegistroAuditoria {
  id: number;
  ocurrido_at: string;
  usuario_id: number | null;
  username: string | null;
  rol: Rol | null;
  accion: string;
  entidad: string | null;
  entidad_id: string | number | null;
  detalle: Record<string, unknown> | null;
  ip: string | null;
  user_agent: string | null;
}

export interface PaginaAuditoria {
  items: RegistroAuditoria[];
  total: number;
  page: number;
  page_size: number;
}

export interface OpcionesAuditoria {
  acciones: string[];
  entidades: string[];
  usuarios: Array<{ id: number; username: string; nombre: string }>;
}

export interface FiltrosAuditoria {
  usuario_id?: number;
  accion?: string;
  entidad?: string;
  entidad_id?: string;
  /** Instante ISO 8601 con zona (inicio del día en Lima). */
  desde?: string;
  /** Instante ISO 8601 con zona (fin del día en Lima). */
  hasta?: string;
  page: number;
  page_size: number;
}

export const auditoriaApi = {
  listar: (f: FiltrosAuditoria, signal?: AbortSignal) =>
    api.get<PaginaAuditoria>("/auditoria", { ...f }, signal),
  opciones: (signal?: AbortSignal) => api.get<OpcionesAuditoria>("/auditoria/opciones", undefined, signal),
};

export const claveAuditoria = {
  lista: (f: FiltrosAuditoria) => ["auditoria", "lista", f] as const,
  opciones: ["auditoria", "opciones"] as const,
};
