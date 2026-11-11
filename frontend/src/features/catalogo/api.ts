import { api } from "../../services/httpClient";

export interface Turno {
  id: number;
  codigo: string;
  orden: number;
  area_ha: number;
  valvula_controlador: string | number;
}

export interface Modulo {
  id: number;
  codigo: string;
  nombre: string;
  area_ha: number;
  turnos: Turno[];
}

export interface Fundo {
  id: number;
  codigo: string;
  nombre: string;
  modulos: Modulo[];
}

export interface MotivoCorreccion {
  codigo: string;
  nombre: string;
  orden: number;
}

export const catalogoApi = {
  fundos: (signal?: AbortSignal) => api.get<Fundo[]>("/fundos", undefined, signal),
  motivos: (signal?: AbortSignal) => api.get<MotivoCorreccion[]>("/motivos-correccion", undefined, signal),
};

export const claveCatalogo = {
  fundos: ["catalogo", "fundos"] as const,
  motivos: ["catalogo", "motivos"] as const,
};
