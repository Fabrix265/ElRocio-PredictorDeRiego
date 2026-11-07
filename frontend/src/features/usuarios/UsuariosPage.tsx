import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { EllipsisVertical, FilterX, KeyRound, Pencil, Power, PowerOff, Search, UserPlus, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { DataTable } from "../../components/ui/DataTable";
import { Dialog } from "../../components/ui/Dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../../components/ui/DropdownMenu";
import { EmptyState } from "../../components/ui/EmptyState";
import { Input } from "../../components/ui/Input";
import { PageHeader } from "../../components/ui/PageHeader";
import { Select } from "../../components/ui/Select";
import { formatearFechaHora } from "../../lib/fechas";
import { ETIQUETA_ROL, ROLES, type Rol } from "../../lib/roles";
import { mensajeDeError } from "../../services/httpClient";
import type { Usuario } from "../../services/tipos";
import { useUsuario } from "../auth/AuthProvider";
import { claveUsuarios, usuariosApi, type FiltrosUsuarios } from "./api";
import { DialogoEditarUsuario, DialogoEstadoUsuario, DialogoNuevoUsuario, DialogoPasswordTemporal } from "./DialogosUsuario";

type Dialogo =
  | { tipo: "nuevo" }
  | { tipo: "editar"; usuario: Usuario }
  | { tipo: "estado"; usuario: Usuario }
  | { tipo: "password"; usuario: Usuario }
  | null;

const OPCIONES_ROL = [{ value: "todos", label: "Todos los roles" }, ...ROLES.map((r) => ({ value: r, label: ETIQUETA_ROL[r] }))];
const OPCIONES_ESTADO = [
  { value: "todos", label: "Activos e inactivos" },
  { value: "activos", label: "Solo activos" },
  { value: "inactivos", label: "Solo inactivos" },
];

function useDebounce<T>(valor: T, ms = 300): T {
  const [v, setV] = useState(valor);
  useEffect(() => {
    const id = window.setTimeout(() => setV(valor), ms);
    return () => window.clearTimeout(id);
  }, [valor, ms]);
  return v;
}

export default function UsuariosPage() {
  const yo = useUsuario();
  const [busqueda, setBusqueda] = useState("");
  const [rol, setRol] = useState("todos");
  const [estado, setEstado] = useState("todos");
  const [dialogo, setDialogo] = useState<Dialogo>(null);
  const q = useDebounce(busqueda.trim());

  const filtros: FiltrosUsuarios = useMemo(
    () => ({
      q: q || undefined,
      rol: rol === "todos" ? undefined : (rol as Rol),
      activo: estado === "todos" ? undefined : estado === "activos",
    }),
    [q, rol, estado],
  );

  const consulta = useQuery({
    queryKey: claveUsuarios.lista(filtros),
    queryFn: ({ signal }) => usuariosApi.listar(filtros, signal),
    placeholderData: keepPreviousData,
  });

  const hayFiltros = !!busqueda || rol !== "todos" || estado !== "todos";
  const limpiar = () => {
    setBusqueda("");
    setRol("todos");
    setEstado("todos");
  };

  const columnas = useMemo<ColumnDef<Usuario, unknown>[]>(
    () => [
      {
        id: "nombre",
        accessorFn: (u) => u.nombre,
        header: "Usuario",
        cell: ({ row: { original: u } }) => (
          <div className="flex flex-col">
            <span className="font-semibold text-texto">
              {u.nombre}
              {u.id === yo.id && <span className="ml-1.5 text-xs font-normal text-texto-3">(tú)</span>}
            </span>
            <span className="text-xs text-texto-3">{u.username}</span>
          </div>
        ),
      },
      { id: "correo", accessorKey: "correo", header: "Correo" },
      {
        id: "rol",
        accessorFn: (u) => ETIQUETA_ROL[u.rol],
        header: "Rol",
      },
      {
        id: "estado",
        accessorFn: (u) => (u.activo ? 0 : 1),
        header: "Estado",
        cell: ({ row: { original: u } }) => (
          <div className="flex flex-wrap gap-1.5">
            {u.activo ? <Badge tono="exito">Activo</Badge> : <Badge tono="neutro">Inactivo</Badge>}
            {u.activo && u.debe_cambiar_password && <Badge tono="aviso" icono={<KeyRound aria-hidden="true" />}>Contraseña temporal</Badge>}
          </div>
        ),
      },
      {
        id: "ultimo_acceso",
        accessorFn: (u) => u.ultimo_acceso_at ?? "",
        header: "Último acceso",
        cell: ({ row: { original: u } }) =>
          u.ultimo_acceso_at ? formatearFechaHora(u.ultimo_acceso_at) : <span className="text-texto-3">Nunca</span>,
      },
      {
        id: "acciones",
        header: () => <span className="sr-only">Acciones</span>,
        enableSorting: false,
        meta: { className: "w-12 text-right" },
        cell: ({ row: { original: u } }) => {
          const esYo = u.id === yo.id;
          return (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variante="fantasma" tamano="icono" aria-label={`Acciones para ${u.nombre}`}>
                  <EllipsisVertical aria-hidden="true" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem icono={<Pencil aria-hidden="true" />} onSelect={() => setDialogo({ tipo: "editar", usuario: u })}>
                  Editar
                </DropdownMenuItem>
                <DropdownMenuItem icono={<KeyRound aria-hidden="true" />} onSelect={() => setDialogo({ tipo: "password", usuario: u })}>
                  Asignar contraseña temporal
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                {u.activo ? (
                  <DropdownMenuItem
                    peligro
                    disabled={esYo}
                    icono={<PowerOff aria-hidden="true" />}
                    onSelect={() => setDialogo({ tipo: "estado", usuario: u })}
                  >
                    {esYo ? "No puedes desactivarte" : "Desactivar"}
                  </DropdownMenuItem>
                ) : (
                  <DropdownMenuItem icono={<Power aria-hidden="true" />} onSelect={() => setDialogo({ tipo: "estado", usuario: u })}>
                    Activar
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          );
        },
      },
    ],
    [yo.id],
  );

  const cerrar = () => setDialogo(null);
  const total = consulta.data?.length ?? 0;

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        antetitulo="Gestión"
        titulo="Usuarios"
        descripcion="Alta de usuarios con contraseña temporal, roles y acceso. Desactivar o cambiar el rol cierra sus sesiones."
        acciones={
          <Button icono={<UserPlus aria-hidden="true" />} onClick={() => setDialogo({ tipo: "nuevo" })}>
            Nuevo usuario
          </Button>
        }
      />

      <Card>
        <div className="flex flex-col gap-3 border-b border-borde p-4 md:flex-row md:items-end">
          <div className="flex min-w-0 flex-1 flex-col gap-1.5">
            <label htmlFor="buscar-usuario" className="text-[13px] font-medium">
              Buscar
            </label>
            <div className="relative">
              <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-texto-3" aria-hidden="true" />
              <Input
                id="buscar-usuario"
                type="search"
                placeholder="Nombre, usuario o correo"
                value={busqueda}
                onChange={(e) => setBusqueda(e.target.value)}
                className="pl-9"
              />
            </div>
          </div>
          <div className="grid grid-cols-1 gap-3 min-[480px]:grid-cols-2 md:flex md:items-end">
            <div className="flex flex-col gap-1.5 md:w-48">
              <span className="text-[13px] font-medium">
                Rol
              </span>
              <Select aria-label="Filtrar por rol" value={rol} onValueChange={setRol} opciones={OPCIONES_ROL} />
            </div>
            <div className="flex flex-col gap-1.5 md:w-48">
              <span className="text-[13px] font-medium">Estado</span>
              <Select aria-label="Filtrar por estado" value={estado} onValueChange={setEstado} opciones={OPCIONES_ESTADO} />
            </div>
          </div>
          {hayFiltros && (
            <Button variante="fantasma" icono={<FilterX aria-hidden="true" />} onClick={limpiar} className="self-start md:self-end">
              Limpiar
            </Button>
          )}
        </div>

        {consulta.isError ? (
          <div className="p-4">
            <Alert tono="error" titulo="No se pudo cargar la lista de usuarios">
              {mensajeDeError(consulta.error)}{" "}
              <button type="button" className="font-semibold underline" onClick={() => void consulta.refetch()}>
                Reintentar
              </button>
            </Alert>
          </div>
        ) : (
          <DataTable
            titulo="Usuarios del sistema"
            columnas={columnas}
            datos={consulta.data}
            cargando={consulta.isPending || (consulta.isFetching && consulta.isPlaceholderData)}
            getRowId={(u) => String(u.id)}
            ordenInicial={[{ id: "nombre", desc: false }]}
            vacio={
              <EmptyState
                compacto
                icono={<Users />}
                titulo={hayFiltros ? "Ningún usuario coincide con los filtros" : "Todavía no hay usuarios"}
                descripcion={hayFiltros ? "Prueba con otra búsqueda o limpia los filtros." : "Crea el primero con “Nuevo usuario”."}
              />
            }
          />
        )}
        {!consulta.isError && consulta.data && (
          <p className="px-4 py-3 text-xs text-texto-2" aria-live="polite">
            {total === 1 ? "1 usuario" : `${total} usuarios`}
          </p>
        )}
      </Card>

      <Dialog open={dialogo !== null} onOpenChange={(abierto) => !abierto && cerrar()}>
        {dialogo?.tipo === "nuevo" && <DialogoNuevoUsuario alTerminar={cerrar} />}
        {dialogo?.tipo === "editar" && (
          <DialogoEditarUsuario key={dialogo.usuario.id} usuario={dialogo.usuario} esUnoMismo={dialogo.usuario.id === yo.id} alTerminar={cerrar} />
        )}
        {dialogo?.tipo === "estado" && <DialogoEstadoUsuario usuario={dialogo.usuario} alTerminar={cerrar} />}
        {dialogo?.tipo === "password" && <DialogoPasswordTemporal key={dialogo.usuario.id} usuario={dialogo.usuario} alTerminar={cerrar} />}
      </Dialog>
    </div>
  );
}
