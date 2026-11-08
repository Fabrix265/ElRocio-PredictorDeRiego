/** Datos de prueba compartidos por los tests de riego y frescura. */
import type { Fundo, Modulo } from "../features/catalogo/api";
import type { Rol } from "../lib/roles";
import type { CicloRiego } from "../services/riego";
import type { Usuario } from "../services/tipos";

export function ciclo(inicio: string, fin: string, m3ha: number, extra: Partial<CicloRiego> = {}): CicloRiego {
  const aMin = (h: string) => Number(h.slice(0, 2)) * 60 + Number(h.slice(3, 5));
  const ini = aMin(inicio);
  let f = aMin(fin);
  if (f <= ini) f += 1440;
  return {
    inicio_min: ini,
    fin_min: f,
    duracion_min: f - ini,
    riego_m3: m3ha * 12.5,
    riego_m3ha: m3ha,
    hora_inicio: inicio,
    hora_fin: fin,
    fin_dia_siguiente: f > 1440,
    ...extra,
  };
}

export function usuarioConRol(rol: Rol): Usuario {
  return {
    id: 1,
    username: rol,
    nombre: `Usuaria ${rol}`,
    correo: `${rol}@example.com`,
    rol,
    activo: true,
    debe_cambiar_password: false,
    ultimo_acceso_at: null,
  };
}

export const MODULO: Modulo = {
  id: 3,
  codigo: "EN01-MOD5",
  nombre: "ENSUEÑO 1 MODULO 5",
  area_ha: 62.8292,
  turnos: [
    { id: 11, codigo: "TE01", orden: 1, area_ha: 13.019, valvula_controlador: "6061000" },
    { id: 12, codigo: "TE02", orden: 2, area_ha: 12.649, valvula_controlador: "6263000" },
  ],
};

export const FUNDO: Fundo = { id: 1, codigo: "EN01", nombre: "ENSUEÑO 1", modulos: [MODULO] };

export function seleccionCon(modulo: Modulo | null = MODULO) {
  return {
    fundos: [FUNDO],
    fundo: FUNDO,
    modulo,
    cargando: false,
    error: false,
    seleccionarFundo: () => {},
    seleccionarModulo: () => {},
  };
}

/** Radix usa APIs de puntero que jsdom no trae. */
export function prepararRadix(): void {
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
}
