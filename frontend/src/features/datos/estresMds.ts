/**
 * Semáforo de estrés hídrico por MDS (contracción diaria máxima del tronco, µm).
 *
 * Rangos del agrónomo (lista de 2026-11): verde < 190, amarillo 190–220, naranja > 220 y rojo
 * "valores aún mayores". El umbral del rojo NO lo dio: 250 µm es provisional hasta que lo confirme.
 * Para ajustar los rangos basta cambiar `UMBRALES_MDS`.
 */
export const UMBRALES_MDS = { moderado: 190, alto: 220, critico: 250 } as const;
// true muestra en la leyenda un asterisco y una nota de umbral provisional (se pidió no mostrarla).
export const CRITICO_PROVISIONAL = false;

export interface NivelMds {
  clave: "sin_estres" | "moderado" | "alto" | "critico";
  nombre: string;
  desde: number;
  hasta: number;
  /** Color del punto y del texto (fuerte). */
  color: string;
  /** Franja de fondo (suave, para no tapar la línea). */
  fondo: string;
}

export const NIVELES_MDS: NivelMds[] = [
  { clave: "sin_estres", nombre: "Sin estrés", desde: 0, hasta: UMBRALES_MDS.moderado, color: "#2F7D45", fondo: "rgba(47, 125, 69, 0.07)" },
  { clave: "moderado", nombre: "Estrés moderado", desde: UMBRALES_MDS.moderado, hasta: UMBRALES_MDS.alto, color: "#B98A00", fondo: "rgba(232, 184, 30, 0.14)" },
  { clave: "alto", nombre: "Estrés alto", desde: UMBRALES_MDS.alto, hasta: UMBRALES_MDS.critico, color: "#D06A00", fondo: "rgba(232, 128, 30, 0.14)" },
  { clave: "critico", nombre: "Estrés crítico", desde: UMBRALES_MDS.critico, hasta: Infinity, color: "#C8291F", fondo: "rgba(200, 41, 31, 0.11)" },
];

export function nivelMds(valor: number): NivelMds {
  return NIVELES_MDS.find((n) => valor < n.hasta) ?? NIVELES_MDS[NIVELES_MDS.length - 1];
}

/** Eje de MDS estable (100–280 µm) para que las franjas se lean igual en cualquier rango de días;
 * se amplía de a 20 µm solo si algún dato se sale. */
export function limitesEjeMds(valores: (number | null)[]): { min: number; max: number } {
  const datos = valores.filter((v): v is number => v != null);
  const bajo = datos.length ? Math.min(...datos) : 100;
  const alto = datos.length ? Math.max(...datos) : 280;
  return {
    min: Math.max(0, Math.min(100, Math.floor((bajo - 10) / 20) * 20)),
    max: Math.max(280, Math.ceil((alto + 10) / 20) * 20),
  };
}
