import { useQuery } from "@tanstack/react-query";

import { claveCronogramas, cronogramasApi } from "../../services/cronogramas";
import { formato } from "./etiquetas";

/**
 * ETo del día anterior de un cronograma (la referencia del plan). El listado ya la trae por fecha;
 * se pide solo ese día y se comparte la caché con la pantalla de cronogramas.
 */
export function useEtoDiaAnterior(moduloId: number | null | undefined, fecha: string | null | undefined) {
  const consulta = useQuery({
    queryKey: claveCronogramas.lista(moduloId ?? 0, fecha ?? "", fecha ?? ""),
    queryFn: ({ signal }) => cronogramasApi.listar(moduloId!, fecha!, fecha!, signal),
    enabled: !!moduloId && !!fecha,
    staleTime: 60_000,
  });
  const fila = consulta.data?.find((c) => c.fecha === fecha);
  return { mm: fila?.eto_dia_anterior_mm ?? null, pronostico: !!fila?.eto_dia_anterior_pronostico };
}

/** "ETo 3.3 mm" o "ETo 3.3 mm (pronóstico)"; "ETo —" si aún no hay dato. */
export function textoEto(eto: { mm: number | null; pronostico: boolean }): string {
  return eto.mm == null ? "ETo —" : `ETo ${formato.eto(eto.mm)} mm${eto.pronostico ? " (pronóstico)" : ""}`;
}
