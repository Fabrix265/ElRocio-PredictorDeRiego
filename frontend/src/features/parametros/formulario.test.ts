import { describe, expect, it } from "vitest";

import type { ParametrosPulsos } from "../../services/pulsos";
import { opcionesN } from "../cronogramas/EditorPlan";
import { aEntrada, aFormulario, sumaCurva } from "./formulario";

const curva3: Record<string, number> = { "3": 4, "4": 5, "5": 5, "18": 5, "19": 5, "20": 4 };
for (let h = 6; h < 18; h++) curva3[String(h)] = 6;

const PARAMETROS: ParametrosPulsos = {
  modulo_id: 1, guardado: true, actualizado_at: null, actualizado_por: null, derivados: null, avisos: [],
  activo: true, textura_suelo: "Arenoso", capacidad_campo: 0.14, punto_marchitez: 0.04, agotamiento_maximo: 0.25,
  infiltracion_basica_mmh: 40, ancho_humedo_m: 2, profundidad_raices_m: 0.5, diametro_bulbo_m: null,
  distancia_hileras_m: 6, distancia_plantas_m: 2, mangueras_por_hilera: 4, separacion_mangueras_m: 0.5,
  distancia_goteros_m: 0.5, caudal_gotero_lh: 1.6, reposo_min_por_hora: 5, eficiencia_aplicacion: 0.85,
  fase_fenologica: "Crecimiento de fruta", agotamiento_por_fase: { Vegetativo: 0.1, "Crecimiento de fruta": 0.05 },
  agotamiento_automatico: true, umbral_etr_1: 2.5, umbral_etr_2: 5, modo_ventana: "automatico_con_respaldo",
  curvas: { "1": { "10": 100 }, "2": { "12": 60, "13": 40 }, "3": curva3 }, ajustar_pulso_al_total: true,
};

describe("formulario de parámetros de riego por pulsos", () => {
  it("muestra fracciones en % y vuelve a la misma entrada", () => {
    const f = aFormulario(PARAMETROS);
    expect(f.numeros.capacidad_campo).toBe("14");
    expect(f.numeros.eficiencia_aplicacion).toBe("85");
    expect(f.numeros.diametro_bulbo_m).toBe("");
    expect(sumaCurva(f, "3")).toBe(100);
    const { datos, errores } = aEntrada(f);
    expect(errores).toEqual([]);
    expect(datos).toMatchObject({
      capacidad_campo: 0.14, eficiencia_aplicacion: 0.85, diametro_bulbo_m: null, mangueras_por_hilera: 4,
      agotamiento_por_fase: { Vegetativo: 0.1, "Crecimiento de fruta": 0.05 },
      curvas: { "1": { "10": 100 }, "2": { "12": 60, "13": 40 }, "3": curva3 },
    });
  });

  it("acepta coma decimal y reporta curvas que no suman 100 y enteros inválidos", () => {
    const f = aFormulario(PARAMETROS);
    f.numeros.caudal_gotero_lh = "1,6";
    f.numeros.mangueras_por_hilera = "3.5";
    f.curvas["2"][13] = "30";
    const { datos, errores } = aEntrada(f);
    expect(datos).toBeNull();
    expect(errores.join(" ")).toContain("Mangueras por hilera");
    expect(errores.join(" ")).toContain("La curva 2 suma 90 %");
    expect(errores.join(" ")).not.toContain("Caudal");
  });
});

describe("opcionesN del editor", () => {
  it("usa las alternativas del backend (hasta 12 con pulsos) y siempre el n actual", () => {
    const alt = Object.fromEntries(Array.from({ length: 12 }, (_, i) => [String(i + 1), Array(i + 1).fill({})]));
    expect(opcionesN(alt, 5)).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);
    expect(opcionesN({ "1": [{}], "2": [{}, {}], "3": [{}] }, 7)).toEqual([1, 2, 7]);
    expect(opcionesN(undefined, 3)).toEqual([3]);
  });
});
