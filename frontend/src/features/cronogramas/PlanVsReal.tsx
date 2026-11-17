import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { CardHeader } from "../../components/ui/Card";
import { Select } from "../../components/ui/Select";
import { Skeleton } from "../../components/ui/Skeleton";
import { hoyLima } from "../../lib/fechas";
import { mensajeDeError } from "../../services/httpClient";
import { claveReportes, reportesApi } from "../../services/reportes";
import type { UnidadAgua } from "../datos/agua";
import { TablaAgua } from "../datos/TablaAgua";

/** Del día del cronograma, por turno: lo que propuso el modelo, el modelo modificado (publicado) y lo real. */
export function PlanVsReal({ moduloId, fecha }: { moduloId: number; fecha: string }) {
  const [unidad, setUnidad] = useState<UnidadAgua>("m3ha");
  const q = useQuery({
    queryKey: claveReportes.agua(moduloId, fecha, fecha),
    queryFn: ({ signal }) => reportesApi.agua(moduloId, fecha, fecha, signal),
  });
  const futuro = fecha >= hoyLima();
  return (
    <>
      <CardHeader titulo="Plan vs real" descripcion={futuro
        ? "El riego real llega del controlador al día siguiente; mientras tanto se ve el provisional (lo planificado)."
        : "Modelo, modelo modificado (publicado) y riego real del controlador, por turno."}
        acciones={<div className="w-28"><Select aria-label="Unidad" value={unidad} onValueChange={(v) => setUnidad(v as UnidadAgua)}
          opciones={[{ value: "m3ha", label: "m³/ha" }, { value: "m3", label: "m³" }]} /></div>} />
      <div className="p-4">
        {q.isPending ? <Skeleton className="h-40" />
          : q.isError ? <Alert tono="error">{mensajeDeError(q.error)} <Button variante="fantasma" disabled={q.isFetching} onClick={() => void q.refetch()}>Reintentar</Button></Alert>
            : <TablaAgua dias={q.data.dias} unidad={unidad} conModelo={q.data.con_modelo} desplegado enlaces={false} />}
      </div>
    </>
  );
}
