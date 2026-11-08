import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CalendarDays, ChevronRight, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { clasesBoton } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { Field } from "../../components/ui/Field";
import { Input } from "../../components/ui/Input";
import { PageHeader } from "../../components/ui/PageHeader";
import { Skeleton } from "../../components/ui/Skeleton";
import { formatearDiaCorto, formatearFechaHora, hoyLima, sumarDias } from "../../lib/fechas";
import { puede } from "../../lib/roles";
import { mensajeDeError } from "../../services/httpClient";
import { claveCronogramas, cronogramasApi } from "../../services/cronogramas";
import { useUsuario } from "../auth/AuthProvider";
import { useSeleccion } from "../catalogo/SeleccionProvider";
import { validarRango } from "../riego/RiegoPage";
import { ETIQUETA_ESTADO, ETIQUETA_ORIGEN_VERSION, MarcasVersion, TONO_ESTADO } from "./etiquetas";

export default function CronogramasPage() {
  const usuario = useUsuario();
  const navigate = useNavigate();
  const { modulo } = useSeleccion();
  const hoy = hoyLima();
  const [rango, setRango] = useState(() => ({ desde: sumarDias(hoy, -30), hasta: sumarDias(hoy, 7) }));
  const errorRango = validarRango(rango.desde, rango.hasta);
  const puedeGenerar = puede(usuario.rol, "generarCronogramas");

  const consulta = useQuery({
    queryKey: claveCronogramas.lista(modulo?.id ?? 0, rango.desde, rango.hasta),
    queryFn: ({ signal }) => cronogramasApi.listar(modulo!.id, rango.desde, rango.hasta, signal),
    enabled: !!modulo && !errorRango,
    placeholderData: keepPreviousData,
  });

  const botonGenerar = puedeGenerar && (
    <Link to="/generar" className={clasesBoton("primario")}>
      <Sparkles aria-hidden="true" />
      Generar
    </Link>
  );

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        antetitulo="Operación"
        titulo="Cronogramas"
        descripcion={
          usuario.rol === "programador"
            ? "Cronogramas publicados por fecha. Toca uno para ver sus ciclos."
            : "Cronogramas por fecha con su estado, versión y marcas. Toca uno para ver el detalle."
        }
        acciones={botonGenerar}
      />
      <Card>
        <div className="grid grid-cols-2 gap-3 border-b border-borde p-4 sm:flex sm:flex-wrap sm:items-end">
          <Field label="Desde" className="sm:w-44">
            <Input type="date" value={rango.desde} onChange={(e) => setRango((r) => ({ ...r, desde: e.target.value }))} />
          </Field>
          <Field label="Hasta" className="sm:w-44">
            <Input type="date" value={rango.hasta} onChange={(e) => setRango((r) => ({ ...r, hasta: e.target.value }))} />
          </Field>
        </div>
        {errorRango ? (
          <div className="p-4">
            <Alert tono="aviso">{errorRango}</Alert>
          </div>
        ) : !modulo ? (
          <EmptyState compacto icono={<CalendarDays />} titulo="Elige un módulo" descripcion="Usa el selector Fundo › Módulo de la cabecera." />
        ) : consulta.isError ? (
          <div className="p-4">
            <Alert tono="error" titulo="No se pudieron cargar los cronogramas">
              {mensajeDeError(consulta.error)}
            </Alert>
          </div>
        ) : consulta.isPending ? (
          <div className="flex flex-col gap-2 p-4" aria-busy="true">
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
            <Skeleton className="h-14" />
          </div>
        ) : consulta.data.length === 0 ? (
          <EmptyState
            compacto
            icono={<CalendarDays />}
            titulo="Sin cronogramas en este rango"
            descripcion={puedeGenerar ? "Genera los de hoy y los próximos días con el modelo." : "Aún no hay cronogramas publicados en estas fechas."}
            accion={botonGenerar}
          />
        ) : (
          <ul className={consulta.isPlaceholderData ? "divide-y divide-borde opacity-60" : "divide-y divide-borde"}>
            {consulta.data.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => navigate(`/cronogramas/${c.id}`)}
                  className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-hundido"
                >
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5 sm:flex-row sm:items-center sm:gap-3">
                    <span className="w-24 shrink-0 text-sm font-semibold text-texto">
                      {formatearDiaCorto(c.fecha)}
                      {c.fecha === hoy && <span className="ml-1 text-xs font-normal text-marca">hoy</span>}
                    </span>
                    <span className="flex flex-wrap items-center gap-1.5">
                      <Badge tono={TONO_ESTADO[c.estado]}>{ETIQUETA_ESTADO[c.estado]}</Badge>
                      {c.tiene_borrador_cambios && <Badge tono="aviso">Cambios sin publicar</Badge>}
                      {c.version && (
                        <span className="text-xs text-texto-2">
                          v{c.version.numero} · {ETIQUETA_ORIGEN_VERSION[c.version.origen]} · {formatearFechaHora(c.version.creado_at)}
                        </span>
                      )}
                    </span>
                    {c.version && <MarcasVersion marcas={c.version} />}
                  </div>
                  <ChevronRight className="size-4 shrink-0 text-texto-3" aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
