import { useMutation } from "@tanstack/react-query";
import { FileDown, FileSpreadsheet } from "lucide-react";

import { Button } from "../../components/ui/Button";
import { notificar } from "../../components/ui/Toast";
import { mensajeDeError } from "../../services/httpClient";
import { reportesApi, type OrdenPlan } from "../../services/reportes";

/** PDF y Excel de la versión visible (el programador exporta siempre la publicada). */
export function BotonesExportar({ cronogramaId, orden = "turno", deshabilitado }: { cronogramaId: number; orden?: OrdenPlan; deshabilitado?: boolean }) {
  const exportar = useMutation({
    mutationFn: (formato: "pdf" | "xlsx") => reportesApi.exportarCronograma(cronogramaId, formato, orden),
    onSuccess: (nombre) => notificar.exito(`Se descargó ${nombre}`),
    onError: (e) => notificar.error(`No se pudo exportar: ${mensajeDeError(e)}`),
  });
  const ocupado = deshabilitado || exportar.isPending;
  return (
    <>
      <Button variante="secundario" disabled={ocupado} onClick={() => exportar.mutate("pdf")}>
        <FileDown aria-hidden="true" />
        PDF
      </Button>
      <Button variante="secundario" disabled={ocupado} onClick={() => exportar.mutate("xlsx")}>
        <FileSpreadsheet aria-hidden="true" />
        Excel
      </Button>
    </>
  );
}
