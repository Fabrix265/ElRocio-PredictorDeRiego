import { useQueries } from "@tanstack/react-query";
import { ArrowRight, CalendarDays, Sparkles } from "lucide-react";
import { Link } from "react-router";

import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { clasesBoton } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { formatearDiaCorto, hoyLima, sumarDias } from "../../lib/fechas";
import { puede } from "../../lib/roles";
import { mensajeDeError } from "../../services/httpClient";
import { claveCronogramas, cronogramasApi } from "../../services/cronogramas";
import { useUsuario } from "../auth/AuthProvider";
import { useSeleccion } from "../catalogo/SeleccionProvider";
import { ETIQUETA_ESTADO, MarcasVersion, TONO_ESTADO, formato } from "../cronogramas/etiquetas";
import { Gantt } from "../cronogramas/Gantt";

/** Cronograma de hoy y de mañana con su Gantt (el programador solo ve los publicados). */
export function useCronogramasHoyManana() {
  const { modulo } = useSeleccion();
  const hoy = hoyLima();
  const fechas = [hoy, sumarDias(hoy, 1)];
  const consultas = useQueries({
    queries: fechas.map((fecha) => ({
      queryKey: claveCronogramas.porFecha(modulo?.id ?? 0, fecha),
      queryFn: ({ signal }: { signal: AbortSignal }) => cronogramasApi.porFecha(modulo!.id, fecha, signal),
      enabled: !!modulo,
    })),
  });
  return { fechas, consultas };
}

export function HoyManana({ fechas, consultas }: ReturnType<typeof useCronogramasHoyManana>) {
  const usuario = useUsuario();
  const { modulo } = useSeleccion();
  const puedeGenerar = puede(usuario.rol, "generarCronogramas");

  return (
    <Card>
      <CardHeader
        titulo="Hoy y mañana"
        descripcion={usuario.rol === "programador" ? "Cronogramas publicados" : "Versión vigente de cada día"}
      />
      <div className="grid grid-cols-1 gap-4 p-4 xl:grid-cols-2">
        {fechas.map((fecha, i) => {
          const q = consultas[i];
          const c = q.data;
          return (
            <section key={fecha} className="flex min-w-0 flex-col gap-2" aria-label={i === 0 ? "Hoy" : "Mañana"}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-sm font-semibold text-texto">
                  {i === 0 ? "Hoy" : "Mañana"} <span className="font-normal text-texto-2">· {formatearDiaCorto(fecha)}</span>
                </h4>
                {c && (
                  <span className="flex items-center gap-1.5">
                    <Badge tono={TONO_ESTADO[c.estado]}>{ETIQUETA_ESTADO[c.estado]}</Badge>
                    {c.version && <span className="text-xs text-texto-2">v{c.version.numero}</span>}
                  </span>
                )}
              </div>
              {!modulo ? <p className="text-sm text-texto-2">Elige un módulo.</p> : q.isPending ? (
                <Skeleton className="h-32" />
              ) : q.isError ? (
                <Alert tono="error">{mensajeDeError(q.error)}</Alert>
              ) : !c || !c.version ? (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed border-borde px-3 py-2 text-xs text-texto-2">
                  <span className="flex items-center gap-1.5">
                    <CalendarDays className="size-4" aria-hidden="true" />
                    {usuario.rol === "programador" ? "Aún no hay cronograma publicado." : "Aún no hay cronograma."}
                  </span>
                  {puedeGenerar && (
                    <Link to="/generar" className={clasesBoton("secundario", "sm")}>
                      <Sparkles aria-hidden="true" /> Generar
                    </Link>
                  )}
                </div>
              ) : (
                <>
                  <MarcasVersion marcas={c.version} />
                  <Gantt turnos={c.version.turnos} compacto />
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-texto-2">
                    <span>
                      {c.version.turnos.reduce((s, t) => s + t.n_ciclos, 0)} ciclos · {formato.m3(c.version.total_m3)} m³
                    </span>
                    <Link to={`/cronogramas/${c.id}`} className="inline-flex items-center gap-1 font-semibold text-marca hover:underline">
                      Ver detalle <ArrowRight className="size-3.5" aria-hidden="true" />
                    </Link>
                  </div>
                </>
              )}
            </section>
          );
        })}
      </div>
    </Card>
  );
}
