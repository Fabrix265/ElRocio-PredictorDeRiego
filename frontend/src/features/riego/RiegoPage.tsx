import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Droplet, FileSpreadsheet } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";

import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button, clasesBoton } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Dialog } from "../../components/ui/Dialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { Field } from "../../components/ui/Field";
import { Input } from "../../components/ui/Input";
import { PageHeader } from "../../components/ui/PageHeader";
import { Skeleton } from "../../components/ui/Skeleton";
import { diasEntre, esDiaValido, formatearDia, hoyLima, listaDias, sumarDias } from "../../lib/fechas";
import { puede } from "../../lib/roles";
import { useAhora } from "../../lib/useAhora";
import { mensajeDeError } from "../../services/httpClient";
import { claveRiego, riegoApi, type RegistroRiego } from "../../services/riego";
import { useUsuario } from "../auth/AuthProvider";
import type { Turno } from "../catalogo/api";
import { useSeleccion } from "../catalogo/SeleccionProvider";
import { ETIQUETA_ESTADO_CELDA, TONO_ESTADO_CELDA, type EstadoCelda } from "./etiquetas";
import { PanelTurnoDia } from "./PanelTurnoDia";
import { TablaRiego, claveTurnoDia, indexarRegistros } from "./TablaRiego";

/** Rango máximo que se pide de una vez (≈ 3 meses × 5 turnos). */
export const MAX_DIAS_RANGO = 92;
const ATAJOS = [7, 14, 30] as const;

/** Valida el rango de fechas del filtro; null si es válido. */
export function validarRango(desde: string, hasta: string): string | null {
  if (!esDiaValido(desde) || !esDiaValido(hasta)) return "Elige las dos fechas.";
  if (desde > hasta) return "«Hasta» debe ser igual o posterior a «Desde».";
  if (diasEntre(desde, hasta) + 1 > MAX_DIAS_RANGO) return `El rango máximo es de ${MAX_DIAS_RANGO} días.`;
  return null;
}

interface Seleccion {
  turno: Turno;
  fecha: string;
  registro: RegistroRiego | null;
}

const LEYENDA: EstadoCelda[] = ["aplicado", "provisional", "sin_riego", "sin_registro"];

export default function RiegoPage() {
  const usuario = useUsuario();
  const { modulo, cargando: cargandoCatalogo } = useSeleccion();
  const hoy = hoyLima(useAhora());
  const [rango, setRango] = useState(() => ({ desde: sumarDias(hoyLima(), -13), hasta: hoyLima() }));
  const [seleccion, setSeleccion] = useState<Seleccion | null>(null);

  const errorRango = validarRango(rango.desde, rango.hasta);
  const turnos = useMemo(() => [...(modulo?.turnos ?? [])].sort((a, b) => a.orden - b.orden), [modulo]);

  const consulta = useQuery({
    queryKey: claveRiego.lista(modulo?.id ?? 0, rango.desde, rango.hasta),
    queryFn: ({ signal }) => riegoApi.listar(modulo!.id, rango.desde, rango.hasta, signal),
    enabled: !!modulo && !errorRango,
    placeholderData: keepPreviousData,
  });

  const registros = useMemo(() => indexarRegistros(consulta.data ?? []), [consulta.data]);
  const dias = useMemo(() => (errorRango ? [] : listaDias(rango.desde, rango.hasta).reverse()), [rango, errorRango]);
  const puedeSubir = puede(usuario.rol, "subirExcelRiego");

  const aplicarAtajo = (n: number) => setRango({ desde: sumarDias(hoy, -(n - 1)), hasta: hoy });

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        antetitulo="Operación"
        titulo="Riego aplicado"
        descripcion={
          modulo
            ? `Riego por turno y día de ${modulo.codigo}, con su estado y ciclos. Toca un turno-día para ver el detalle${puede(usuario.rol, "verVersionesRiego") ? " y su historial de versiones" : ""}.`
            : "Riego por turno y día, con su estado y ciclos."
        }
        acciones={
          puedeSubir && (
            <Link to="/riego/cargas/nueva" className={clasesBoton("primario")}>
              <FileSpreadsheet aria-hidden="true" />
              Cargar Excel
            </Link>
          )
        }
      />

      <Card>
        <div className="flex flex-col gap-3 border-b border-borde p-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="grid grid-cols-2 gap-3 sm:flex sm:flex-wrap sm:items-end">
            <Field label="Desde" className="sm:w-44">
              <Input
                type="date"
                value={rango.desde}
                max={rango.hasta || hoy}
                onChange={(e) => setRango((r) => ({ ...r, desde: e.target.value }))}
              />
            </Field>
            <Field label="Hasta" className="sm:w-44">
              <Input
                type="date"
                value={rango.hasta}
                min={rango.desde || undefined}
                onChange={(e) => setRango((r) => ({ ...r, hasta: e.target.value }))}
              />
            </Field>
            <div className="col-span-2 flex gap-2 sm:col-span-1">
              {ATAJOS.map((n) => (
                <Button key={n} variante="secundario" tamano="sm" className="h-10" onClick={() => aplicarAtajo(n)}>
                  {n} días
                </Button>
              ))}
            </div>
          </div>
          <ul className="flex flex-wrap gap-1.5" aria-label="Leyenda de estados">
            {LEYENDA.map((e) => (
              <li key={e}>
                <Badge tono={TONO_ESTADO_CELDA[e]}>{ETIQUETA_ESTADO_CELDA[e]}</Badge>
              </li>
            ))}
          </ul>
        </div>

        {errorRango ? (
          <div className="p-4">
            <Alert tono="aviso">{errorRango}</Alert>
          </div>
        ) : !modulo ? (
          cargandoCatalogo ? (
            <div className="flex flex-col gap-2 p-4" aria-busy="true">
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </div>
          ) : (
            <EmptyState compacto icono={<Droplet />} titulo="Elige un módulo" descripcion="Usa el selector Fundo › Módulo de la cabecera." />
          )
        ) : consulta.isError ? (
          <div className="p-4">
            <Alert tono="error" titulo="No se pudo cargar el riego">
              {mensajeDeError(consulta.error)}{" "}
              <button type="button" className="font-semibold underline" onClick={() => void consulta.refetch()}>
                Reintentar
              </button>
            </Alert>
          </div>
        ) : consulta.isPending ? (
          <div className="flex flex-col gap-2 p-4" aria-busy="true">
            {Array.from({ length: 4 }, (_, i) => (
              <Skeleton key={i} className="h-16" />
            ))}
          </div>
        ) : consulta.data.length === 0 ? (
          <EmptyState
            compacto
            icono={<Droplet />}
            titulo="Sin riego registrado en este rango"
            descripcion={`No hay registros de ${modulo.codigo} entre el ${formatearDia(rango.desde)} y el ${formatearDia(rango.hasta)}.`}
            accion={
              puedeSubir && (
                <Link to="/riego/cargas/nueva" className={clasesBoton("secundario", "sm")}>
                  <FileSpreadsheet aria-hidden="true" />
                  Cargar Excel
                </Link>
              )
            }
          />
        ) : (
          <div aria-busy={consulta.isFetching || undefined} className={consulta.isPlaceholderData ? "opacity-60" : undefined}>
            <TablaRiego
              dias={dias}
              turnos={turnos}
              registros={registros}
              seleccionado={seleccion ? claveTurnoDia(seleccion.turno.id, seleccion.fecha) : null}
              onSeleccionar={(turno, fecha, registro) => setSeleccion({ turno, fecha, registro })}
              abrirSinRegistro={puede(usuario.rol, "editarRiego")}
            />
          </div>
        )}
      </Card>

      <Dialog open={seleccion !== null} onOpenChange={(abierto) => !abierto && setSeleccion(null)}>
        {seleccion && (
          <PanelTurnoDia
            turno={seleccion.turno}
            fecha={seleccion.fecha}
            registro={seleccion.registro}
            verVersiones={puede(usuario.rol, "verVersionesRiego")}
          />
        )}
      </Dialog>
    </div>
  );
}
