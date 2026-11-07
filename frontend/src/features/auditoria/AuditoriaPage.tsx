import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { ChevronLeft, ChevronRight, FilterX, History } from "lucide-react";
import { useMemo, useState } from "react";

import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { DataTable } from "../../components/ui/DataTable";
import { Dialog } from "../../components/ui/Dialog";
import { EmptyState } from "../../components/ui/EmptyState";
import { Field } from "../../components/ui/Field";
import { Input } from "../../components/ui/Input";
import { PageHeader } from "../../components/ui/PageHeader";
import { Select } from "../../components/ui/Select";
import { formatearFechaHora, hoyLima, limiteDiaLima } from "../../lib/fechas";
import { mensajeDeError } from "../../services/httpClient";
import { auditoriaApi, claveAuditoria, type FiltrosAuditoria, type RegistroAuditoria } from "./api";
import { etiquetaAccion, etiquetaEntidad, etiquetaRol, tonoAccion } from "./etiquetas";
import { PanelDetalle } from "./PanelDetalle";

const TAMANO_PAGINA = 50;
const TODOS = "todos";

interface Filtros {
  usuario: string;
  accion: string;
  entidad: string;
  desde: string;
  hasta: string;
}

const FILTROS_VACIOS: Filtros = { usuario: TODOS, accion: TODOS, entidad: TODOS, desde: "", hasta: "" };

export default function AuditoriaPage() {
  const [filtros, setFiltros] = useState<Filtros>(FILTROS_VACIOS);
  const [pagina, setPagina] = useState(1);
  const [seleccionado, setSeleccionado] = useState<RegistroAuditoria | null>(null);
  const hoy = hoyLima();

  const cambiar = (parcial: Partial<Filtros>) => {
    setFiltros((f) => ({ ...f, ...parcial }));
    setPagina(1);
  };

  const rangoInvalido = !!filtros.desde && !!filtros.hasta && filtros.desde > filtros.hasta;

  const parametros: FiltrosAuditoria = useMemo(
    () => ({
      usuario_id: filtros.usuario !== TODOS ? Number(filtros.usuario) : undefined,
      accion: filtros.accion !== TODOS ? filtros.accion : undefined,
      entidad: filtros.entidad !== TODOS ? filtros.entidad : undefined,
      desde: filtros.desde ? limiteDiaLima(filtros.desde, "inicio") : undefined,
      hasta: filtros.hasta ? limiteDiaLima(filtros.hasta, "fin") : undefined,
      page: pagina,
      page_size: TAMANO_PAGINA,
    }),
    [filtros, pagina],
  );

  const opciones = useQuery({
    queryKey: claveAuditoria.opciones,
    queryFn: ({ signal }) => auditoriaApi.opciones(signal),
    staleTime: 5 * 60 * 1000,
  });

  const consulta = useQuery({
    queryKey: claveAuditoria.lista(parametros),
    queryFn: ({ signal }) => auditoriaApi.listar(parametros, signal),
    placeholderData: keepPreviousData,
    enabled: !rangoInvalido,
  });

  const opcionesUsuario = useMemo(
    () => [
      { value: TODOS, label: "Todos los usuarios" },
      ...(opciones.data?.usuarios ?? []).map((u) => ({ value: String(u.id), label: `${u.nombre} (${u.username})` })),
    ],
    [opciones.data],
  );
  const opcionesAccion = useMemo(
    () => [
      { value: TODOS, label: "Todas las acciones" },
      ...(opciones.data?.acciones ?? []).map((a) => ({ value: a, label: etiquetaAccion(a) })),
    ],
    [opciones.data],
  );
  const opcionesEntidad = useMemo(
    () => [
      { value: TODOS, label: "Todas las entidades" },
      ...(opciones.data?.entidades ?? []).map((e) => ({ value: e, label: etiquetaEntidad(e) })),
    ],
    [opciones.data],
  );

  const columnas = useMemo<ColumnDef<RegistroAuditoria, unknown>[]>(
    () => [
      {
        id: "ocurrido_at",
        header: "Fecha y hora",
        cell: ({ row: { original: r } }) => <span className="cifras">{formatearFechaHora(r.ocurrido_at)}</span>,
      },
      {
        id: "usuario",
        header: "Usuario",
        cell: ({ row: { original: r } }) => (
          <div className="flex flex-col">
            <span className="font-medium">{r.username ?? "Sistema"}</span>
            <span className="text-xs text-texto-3">{etiquetaRol(r.rol)}</span>
          </div>
        ),
      },
      {
        id: "accion",
        header: "Acción",
        cell: ({ row: { original: r } }) => <Badge tono={tonoAccion(r.accion)}>{etiquetaAccion(r.accion)}</Badge>,
      },
      {
        id: "entidad",
        header: "Entidad",
        cell: ({ row: { original: r } }) =>
          r.entidad ? (
            <span>
              {etiquetaEntidad(r.entidad)}
              {r.entidad_id != null && <span className="text-texto-3"> #{r.entidad_id}</span>}
            </span>
          ) : (
            <span className="text-texto-3">—</span>
          ),
      },
      {
        id: "ip",
        header: "IP",
        cell: ({ row: { original: r } }) => <span className="font-mono text-xs text-texto-2">{r.ip ?? "—"}</span>,
      },
    ],
    [],
  );

  const datos = consulta.data;
  const total = datos?.total ?? 0;
  const totalPaginas = Math.max(1, Math.ceil(total / TAMANO_PAGINA));
  const desdeN = total === 0 ? 0 : (pagina - 1) * TAMANO_PAGINA + 1;
  const hastaN = Math.min(pagina * TAMANO_PAGINA, total);
  const hayFiltros = JSON.stringify(filtros) !== JSON.stringify(FILTROS_VACIOS);

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        antetitulo="Gestión"
        titulo="Auditoría"
        descripcion="Registro de solo lectura de quién hizo qué y cuándo (hora de Lima). Toca una fila para ver el detalle."
      />

      <Card>
        <div className="grid grid-cols-1 gap-3 border-b border-borde p-4 sm:grid-cols-2 lg:grid-cols-3 lg:items-end 2xl:grid-cols-[repeat(3,minmax(0,1fr))_160px_160px_auto]">
          <Field label="Usuario">
            <Select value={filtros.usuario} onValueChange={(v) => cambiar({ usuario: v })} opciones={opcionesUsuario} disabled={opciones.isPending} />
          </Field>
          <Field label="Acción">
            <Select value={filtros.accion} onValueChange={(v) => cambiar({ accion: v })} opciones={opcionesAccion} disabled={opciones.isPending} />
          </Field>
          <Field label="Entidad">
            <Select value={filtros.entidad} onValueChange={(v) => cambiar({ entidad: v })} opciones={opcionesEntidad} disabled={opciones.isPending} />
          </Field>
          <Field label="Desde">
            <Input type="date" value={filtros.desde} max={filtros.hasta || hoy} onChange={(e) => cambiar({ desde: e.target.value })} />
          </Field>
          <Field label="Hasta" error={rangoInvalido ? "Debe ser igual o posterior a “Desde”." : undefined}>
            <Input type="date" value={filtros.hasta} min={filtros.desde || undefined} max={hoy} onChange={(e) => cambiar({ hasta: e.target.value })} />
          </Field>
          <div className="flex items-end">
            <Button
              variante="fantasma"
              icono={<FilterX aria-hidden="true" />}
              onClick={() => {
                setFiltros(FILTROS_VACIOS);
                setPagina(1);
              }}
              disabled={!hayFiltros}
            >
              Limpiar
            </Button>
          </div>
        </div>

        {opciones.isError && (
          <div className="px-4 pt-4">
            <Alert tono="aviso">No se pudieron cargar las opciones de filtro: {mensajeDeError(opciones.error)}</Alert>
          </div>
        )}

        {consulta.isError ? (
          <div className="p-4">
            <Alert tono="error" titulo="No se pudo cargar la auditoría">
              {mensajeDeError(consulta.error)}{" "}
              <button type="button" className="font-semibold underline" onClick={() => void consulta.refetch()}>
                Reintentar
              </button>
            </Alert>
          </div>
        ) : (
          <DataTable
            titulo="Registros de auditoría"
            columnas={columnas}
            datos={rangoInvalido ? [] : datos?.items}
            cargando={!rangoInvalido && (consulta.isPending || (consulta.isFetching && consulta.isPlaceholderData))}
            sinOrden
            getRowId={(r) => String(r.id)}
            onFilaClick={setSeleccionado}
            etiquetaFila={(r) => `Ver detalle: ${etiquetaAccion(r.accion)}, ${formatearFechaHora(r.ocurrido_at)}`}
            filaSeleccionadaId={seleccionado ? String(seleccionado.id) : null}
            vacio={
              <EmptyState
                compacto
                icono={<History />}
                titulo={hayFiltros ? "Sin registros con estos filtros" : "Todavía no hay registros"}
                descripcion={hayFiltros ? "Amplía el rango de fechas o limpia los filtros." : "Las acciones de los usuarios aparecerán aquí."}
              />
            }
          />
        )}

        {!consulta.isError && !rangoInvalido && total > 0 && (
          <nav aria-label="Paginación" className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
            <p className="cifras text-xs text-texto-2" aria-live="polite">
              {desdeN.toLocaleString("es-PE")}–{hastaN.toLocaleString("es-PE")} de {total.toLocaleString("es-PE")} registros
            </p>
            <div className="flex items-center gap-2">
              <Button
                variante="secundario"
                tamano="sm"
                icono={<ChevronLeft aria-hidden="true" />}
                disabled={pagina <= 1 || consulta.isFetching}
                onClick={() => setPagina((p) => Math.max(1, p - 1))}
              >
                Anterior
              </Button>
              <span className="cifras text-xs text-texto-2">
                Página {pagina} de {totalPaginas}
              </span>
              <Button
                variante="secundario"
                tamano="sm"
                disabled={pagina >= totalPaginas || consulta.isFetching}
                onClick={() => setPagina((p) => Math.min(totalPaginas, p + 1))}
                className="flex-row-reverse"
                icono={<ChevronRight aria-hidden="true" />}
              >
                Siguiente
              </Button>
            </div>
          </nav>
        )}
      </Card>

      <Dialog open={seleccionado !== null} onOpenChange={(abierto) => !abierto && setSeleccionado(null)}>
        {seleccionado && <PanelDetalle registro={seleccionado} />}
      </Dialog>
    </div>
  );
}
