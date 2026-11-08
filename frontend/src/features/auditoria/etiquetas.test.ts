import { describe, expect, it } from "vitest";

import { etiquetaAccion, etiquetaCampo, etiquetaEntidad, formatearValor } from "./etiquetas";

describe("etiquetas de auditoría de F2", () => {
  it("nombra en español las acciones y entidades de la carga de Excel y del reproceso", () => {
    expect(etiquetaAccion("excel_subido")).toBe("Excel de riego subido");
    expect(etiquetaAccion("excel_confirmado")).toBe("Excel de riego confirmado");
    expect(etiquetaAccion("excel_descartado")).toBe("Excel de riego descartado");
    expect(etiquetaAccion("meteo_excel_pisado")).toBe("Lecturas del Excel histórico reemplazadas por WeatherLink");
    // Las entidades que guarda el backend (auditoria_service.ENTIDAD_*), no nombres técnicos.
    expect(etiquetaEntidad("carga_riego")).toBe("Carga de Excel de riego");
    expect(etiquetaEntidad("ingesta_corrida")).toBe("Corrida de ingesta");
  });

  it("traduce los campos del detalle de una carga", () => {
    expect(etiquetaCampo("tamano_bytes")).toBe("Tamaño (bytes)");
    expect(etiquetaCampo("versiones_reemplazadas")).toBe("Versiones reemplazadas");
    expect(formatearValor("previsualizada", "estado_anterior")).toBe("Vista previa");
  });
});
