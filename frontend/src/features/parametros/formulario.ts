import type { ModoVentana, ParametrosPulsos, ParametrosPulsosEntrada } from "../../services/pulsos";

/** Campos numéricos del formulario. ``pct``: se muestra en % y se guarda como fracción. */
export interface CampoNumero {
  clave: keyof ParametrosPulsosEntrada;
  etiqueta: string;
  unidad: string;
  pct?: boolean;
  entero?: boolean;
  opcional?: boolean;
  ayuda?: string;
}

export const CAMPOS_SUELO: CampoNumero[] = [
  { clave: "capacidad_campo", etiqueta: "Capacidad de campo (θCC)", unidad: "%", pct: true },
  { clave: "punto_marchitez", etiqueta: "Punto de marchitez (θPMP)", unidad: "%", pct: true },
  { clave: "agotamiento_maximo", etiqueta: "Agotamiento máximo tolerable", unidad: "%", pct: true },
  { clave: "infiltracion_basica_mmh", etiqueta: "Infiltración básica (VIB)", unidad: "mm/h" },
  { clave: "ancho_humedo_m", etiqueta: "Ancho efectivo de humedad por hilera", unidad: "m" },
  { clave: "profundidad_raices_m", etiqueta: "Profundidad efectiva de raíces", unidad: "m" },
  { clave: "diametro_bulbo_m", etiqueta: "Diámetro de bulbo", unidad: "m", opcional: true, ayuda: "Vacío = distancia entre goteros" },
];

export const CAMPOS_SISTEMA: CampoNumero[] = [
  { clave: "distancia_hileras_m", etiqueta: "Distancia entre hileras", unidad: "m" },
  { clave: "distancia_plantas_m", etiqueta: "Distancia entre plantas", unidad: "m" },
  { clave: "mangueras_por_hilera", etiqueta: "Mangueras por hilera", unidad: "", entero: true },
  { clave: "separacion_mangueras_m", etiqueta: "Separación entre mangueras", unidad: "m" },
  { clave: "distancia_goteros_m", etiqueta: "Distancia entre goteros", unidad: "m" },
  { clave: "caudal_gotero_lh", etiqueta: "Caudal del gotero", unidad: "L/h" },
  { clave: "reposo_min_por_hora", etiqueta: "Reposo / cambio de válvulas", unidad: "min por hora" },
  { clave: "eficiencia_aplicacion", etiqueta: "Eficiencia de aplicación (Ea)", unidad: "%", pct: true },
];

export const CAMPOS_VENTANA: CampoNumero[] = [
  { clave: "umbral_etr_1", etiqueta: "Umbral 1 de ETr (curva 1 por debajo)", unidad: "mm/día" },
  { clave: "umbral_etr_2", etiqueta: "Umbral 2 de ETr (curva 3 por encima)", unidad: "mm/día" },
];

export const MODOS: { value: ModoVentana; label: string }[] = [
  { value: "automatico_con_respaldo", label: "Automático con respaldo" },
  { value: "automatico", label: "Automático" },
  { value: "curva_1", label: "Forzar curva 1" },
  { value: "curva_2", label: "Forzar curva 2" },
  { value: "curva_3", label: "Forzar curva 3" },
];

/** Horas con su fila en la tabla de curvas (03:00 a 20:00, inicio de cada hora). */
export const HORAS = Array.from({ length: 18 }, (_, i) => i + 3);
export const CURVAS = ["1", "2", "3"] as const;

export interface Formulario {
  activo: boolean;
  textura_suelo: string;
  fase_fenologica: string;
  modo_ventana: ModoVentana;
  agotamiento_automatico: boolean;
  ajustar_pulso_al_total: boolean;
  numeros: Record<string, string>;
  fases: { fase: string; pct: string }[];
  curvas: Record<string, Record<number, string>>;
}

const texto = (v: number | null | undefined, pct = false) =>
  v == null ? "" : String(Number((pct ? v * 100 : v).toFixed(6)));

export function aFormulario(p: ParametrosPulsos): Formulario {
  const numeros: Record<string, string> = {};
  for (const c of [...CAMPOS_SUELO, ...CAMPOS_SISTEMA, ...CAMPOS_VENTANA]) {
    numeros[c.clave] = texto(p[c.clave] as number | null, c.pct);
  }
  return {
    activo: p.activo,
    textura_suelo: p.textura_suelo,
    fase_fenologica: p.fase_fenologica,
    modo_ventana: p.modo_ventana,
    agotamiento_automatico: p.agotamiento_automatico,
    ajustar_pulso_al_total: p.ajustar_pulso_al_total,
    numeros,
    fases: Object.entries(p.agotamiento_por_fase).map(([fase, v]) => ({ fase, pct: texto(v, true) })),
    curvas: Object.fromEntries(CURVAS.map((c) => [c, Object.fromEntries(HORAS.map((h) => [h, texto(p.curvas[c]?.[String(h)])]))])),
  };
}

export function sumaCurva(f: Formulario, curva: string): number {
  return HORAS.reduce((s, h) => s + (Number(f.curvas[curva][h]) || 0), 0);
}

/** Formulario → cuerpo del PUT, o la lista de errores (las mismas reglas básicas que el backend). */
export function aEntrada(f: Formulario): { datos: ParametrosPulsosEntrada | null; errores: string[] } {
  const errores: string[] = [];
  const valores: Record<string, number | null> = {};
  for (const c of [...CAMPOS_SUELO, ...CAMPOS_SISTEMA, ...CAMPOS_VENTANA]) {
    const crudo = (f.numeros[c.clave] ?? "").trim().replace(",", ".");
    if (crudo === "" && c.opcional) {
      valores[c.clave] = null;
      continue;
    }
    const n = Number(crudo);
    if (crudo === "" || !Number.isFinite(n) || n < 0 || (c.entero && !Number.isInteger(n))) {
      errores.push(`${c.etiqueta}: ingresa un número${c.entero ? " entero" : ""} válido`);
      continue;
    }
    valores[c.clave] = c.pct ? n / 100 : n;
  }
  if (!f.textura_suelo.trim()) errores.push("Indica la textura del suelo");
  const fases: Record<string, number> = {};
  for (const { fase, pct } of f.fases) {
    const n = Number(pct.trim().replace(",", "."));
    if (!fase.trim() || pct.trim() === "" || !Number.isFinite(n) || n <= 0) errores.push(`Agotamiento de «${fase}»: ingresa un % mayor que 0`);
    else fases[fase.trim()] = n / 100;
  }
  const curvas: Record<string, Record<string, number>> = {};
  for (const c of CURVAS) {
    curvas[c] = {};
    for (const h of HORAS) {
      const crudo = (f.curvas[c][h] ?? "").trim().replace(",", ".");
      if (crudo === "") continue;
      const n = Number(crudo);
      if (!Number.isFinite(n) || n < 0 || n > 100) errores.push(`Curva ${c}, ${String(h).padStart(2, "0")}:00: % entre 0 y 100`);
      else curvas[c][String(h)] = n;
    }
    const suma = Object.values(curvas[c]).reduce((s, x) => s + x, 0);
    if (Math.abs(suma - 100) > 0.01) errores.push(`La curva ${c} suma ${Number(suma.toFixed(2))} % y debe sumar 100 %`);
  }
  if (errores.length) return { datos: null, errores };
  return {
    errores,
    datos: {
      activo: f.activo,
      textura_suelo: f.textura_suelo.trim(),
      fase_fenologica: f.fase_fenologica,
      modo_ventana: f.modo_ventana,
      agotamiento_automatico: f.agotamiento_automatico,
      ajustar_pulso_al_total: f.ajustar_pulso_al_total,
      agotamiento_por_fase: fases,
      curvas,
      ...(valores as Record<string, number>),
      diametro_bulbo_m: valores.diametro_bulbo_m ?? null,
    } as ParametrosPulsosEntrada,
  };
}
