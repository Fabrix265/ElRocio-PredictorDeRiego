import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";

import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { DialogClose, DialogContent } from "../../components/ui/Dialog";
import { Field } from "../../components/ui/Field";
import { Input } from "../../components/ui/Input";
import { Select } from "../../components/ui/Select";
import { notificar } from "../../components/ui/Toast";
import { generarPasswordTemporal } from "../../lib/password";
import { ETIQUETA_ROL, ROLES } from "../../lib/roles";
import { mensajeDeError } from "../../services/httpClient";
import type { Usuario } from "../../services/tipos";
import { claveUsuarios, usuariosApi, type CambiosUsuario } from "./api";
import { CamposPasswordTemporal } from "./CamposPasswordTemporal";
import {
  CORREO_MAX,
  crearEsquemaPasswordTemporal,
  esquemaEditarUsuario,
  esquemaNuevoUsuario,
  type DatosEditarUsuario,
  type DatosNuevoUsuario,
  type DatosPasswordTemporal,
  NOMBRE_MAX,
  USERNAME_MAX,
} from "./esquemas";

const OPCIONES_ROL = ROLES.map((r) => ({ value: r, label: ETIQUETA_ROL[r] }));

function useInvalidarUsuarios() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: claveUsuarios.todos });
}

const CancelarBtn = () => (
  <DialogClose asChild>
    <Button variante="secundario">Cancelar</Button>
  </DialogClose>
);

// ---------------------------------------------------------------------------
// Alta
// ---------------------------------------------------------------------------

export function DialogoNuevoUsuario({ alTerminar }: { alTerminar: () => void }) {
  const invalidar = useInvalidarUsuarios();
  const {
    register,
    handleSubmit,
    control,
    setValue,
    formState: { errors },
  } = useForm<DatosNuevoUsuario>({
    resolver: zodResolver(esquemaNuevoUsuario),
    defaultValues: { username: "", nombre: "", correo: "", rol: "programador", password_temporal: "", confirmar: "" },
  });
  const [password, username] = useWatch({ control, name: ["password_temporal", "username"] });

  const mutacion = useMutation({
    mutationFn: ({ confirmar: _c, ...datos }: DatosNuevoUsuario) =>
      usuariosApi.crear({ ...datos, username: datos.username.trim().toLowerCase(), correo: datos.correo.trim() }),
    onSuccess: async (u) => {
      await invalidar();
      notificar.exito("Usuario creado", `${u.nombre} deberá cambiar la contraseña temporal al ingresar.`);
      alTerminar();
    },
  });

  const generar = () => {
    const clave = generarPasswordTemporal();
    setValue("password_temporal", clave, { shouldValidate: true });
    setValue("confirmar", clave, { shouldValidate: true });
  };

  return (
    <DialogContent
      titulo="Nuevo usuario"
      descripcion="Se crea con una contraseña temporal que deberá cambiar en su primer ingreso."
      ancho="lg"
      pie={
        <>
          <CancelarBtn />
          <Button type="submit" form="form-nuevo-usuario" cargando={mutacion.isPending}>
            Crear usuario
          </Button>
        </>
      }
    >
      <form
        id="form-nuevo-usuario"
        noValidate
        onSubmit={handleSubmit((d) => mutacion.mutate(d))}
        className="grid grid-cols-1 gap-4 sm:grid-cols-2"
      >
        {mutacion.isError && (
          <Alert tono="error" className="sm:col-span-2">
            {mensajeDeError(mutacion.error)}
          </Alert>
        )}
        <Field label="Nombre completo" error={errors.nombre?.message} requerido className="sm:col-span-2">
          <Input autoComplete="off" autoFocus maxLength={NOMBRE_MAX} {...register("nombre")} />
        </Field>
        <Field
          label="Usuario"
          error={errors.username?.message}
          requerido
          ayuda="Con este nombre ingresará al sistema. Se guarda en minúsculas."
        >
          {/* `lowercase` muestra lo mismo que se guardará (el esquema lo pasa a minúsculas). */}
          <Input
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            maxLength={USERNAME_MAX}
            className="lowercase"
            {...register("username")}
          />
        </Field>
        <Field label="Rol" error={errors.rol?.message} requerido>
          <Controller
            control={control}
            name="rol"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange} opciones={OPCIONES_ROL} ref={field.ref} />
            )}
          />
        </Field>
        <Field label="Correo" error={errors.correo?.message} requerido className="sm:col-span-2" ayuda="Recibe las notificaciones y el enlace para recuperar la contraseña.">
          <Input type="email" autoComplete="off" inputMode="email" maxLength={CORREO_MAX} {...register("correo")} />
        </Field>
        <div className="sm:col-span-2">
          <CamposPasswordTemporal
            registroPassword={register("password_temporal")}
            registroConfirmar={register("confirmar")}
            errorPassword={errors.password_temporal?.message}
            errorConfirmar={errors.confirmar?.message}
            valor={password ?? ""}
            username={username}
            alGenerar={generar}
          />
        </div>
      </form>
    </DialogContent>
  );
}

// ---------------------------------------------------------------------------
// Edición
// ---------------------------------------------------------------------------

export function DialogoEditarUsuario({
  usuario,
  esUnoMismo,
  alTerminar,
}: {
  usuario: Usuario;
  esUnoMismo: boolean;
  alTerminar: () => void;
}) {
  const invalidar = useInvalidarUsuarios();
  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<DatosEditarUsuario>({
    resolver: zodResolver(esquemaEditarUsuario),
    defaultValues: { nombre: usuario.nombre, correo: usuario.correo, rol: usuario.rol },
  });
  const rol = useWatch({ control, name: "rol" });

  const mutacion = useMutation({
    mutationFn: (cambios: CambiosUsuario) => usuariosApi.editar(usuario.id, cambios),
    onSuccess: async () => {
      await invalidar();
      notificar.exito("Cambios guardados");
      alTerminar();
    },
  });

  const enviar = handleSubmit((d) => {
    const cambios: CambiosUsuario = {};
    if (d.nombre.trim() !== usuario.nombre) cambios.nombre = d.nombre.trim();
    if (d.correo.trim() !== usuario.correo) cambios.correo = d.correo.trim();
    if (d.rol !== usuario.rol) cambios.rol = d.rol;
    if (Object.keys(cambios).length === 0) {
      notificar.info("No hay cambios para guardar");
      alTerminar();
      return;
    }
    mutacion.mutate(cambios);
  });

  return (
    <DialogContent
      titulo="Editar usuario"
      descripcion={
        <>
          Usuario <span className="font-semibold text-texto">{usuario.username}</span> (no se puede cambiar).
        </>
      }
      pie={
        <>
          <CancelarBtn />
          <Button type="submit" form="form-editar-usuario" cargando={mutacion.isPending}>
            Guardar cambios
          </Button>
        </>
      }
    >
      <form id="form-editar-usuario" noValidate onSubmit={enviar} className="flex flex-col gap-4">
        {mutacion.isError && <Alert tono="error">{mensajeDeError(mutacion.error)}</Alert>}
        <Field label="Nombre completo" error={errors.nombre?.message} requerido>
          <Input autoComplete="off" maxLength={NOMBRE_MAX} {...register("nombre")} />
        </Field>
        <Field label="Correo" error={errors.correo?.message} requerido>
          <Input type="email" autoComplete="off" inputMode="email" maxLength={CORREO_MAX} {...register("correo")} />
        </Field>
        <Field label="Rol" error={errors.rol?.message} requerido>
          <Controller
            control={control}
            name="rol"
            render={({ field }) => (
              <Select value={field.value} onValueChange={field.onChange} opciones={OPCIONES_ROL} ref={field.ref} />
            )}
          />
        </Field>
        {rol !== usuario.rol && (
          <Alert tono="aviso">
            {esUnoMismo
              ? "Estás cambiando tu propio rol: perderás el acceso a esta pantalla y tendrás que volver a ingresar."
              : "Al cambiar el rol se cerrarán sus sesiones abiertas y tendrá que volver a ingresar."}
          </Alert>
        )}
      </form>
    </DialogContent>
  );
}

// ---------------------------------------------------------------------------
// Activar / desactivar
// ---------------------------------------------------------------------------

export function DialogoEstadoUsuario({ usuario, alTerminar }: { usuario: Usuario; alTerminar: () => void }) {
  const invalidar = useInvalidarUsuarios();
  const desactivar = usuario.activo;
  const mutacion = useMutation({
    mutationFn: () => usuariosApi.editar(usuario.id, { activo: !usuario.activo }),
    onSuccess: async () => {
      await invalidar();
      notificar.exito(desactivar ? "Usuario desactivado" : "Usuario activado", usuario.nombre);
      alTerminar();
    },
  });

  return (
    <DialogContent
      titulo={desactivar ? `¿Desactivar a ${usuario.nombre}?` : `¿Activar a ${usuario.nombre}?`}
      ancho="sm"
      pie={
        <>
          <CancelarBtn />
          <Button variante={desactivar ? "peligro" : "primario"} cargando={mutacion.isPending} onClick={() => mutacion.mutate()}>
            {desactivar ? "Desactivar" : "Activar"}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3 text-[13px] text-texto-2">
        {mutacion.isError && <Alert tono="error">{mensajeDeError(mutacion.error)}</Alert>}
        <p>
          {desactivar
            ? "Se cerrarán sus sesiones de inmediato y no podrá ingresar ni recuperar su contraseña hasta que lo vuelvas a activar. Su historial se conserva."
            : "Podrá volver a ingresar con su contraseña actual. Si no la recuerda, asígnale una temporal."}
        </p>
      </div>
    </DialogContent>
  );
}

// ---------------------------------------------------------------------------
// Contraseña temporal
// ---------------------------------------------------------------------------

export function DialogoPasswordTemporal({ usuario, alTerminar }: { usuario: Usuario; alTerminar: () => void }) {
  const esquema = useMemo(() => crearEsquemaPasswordTemporal(usuario.username), [usuario.username]);
  const invalidar = useInvalidarUsuarios();
  const {
    register,
    handleSubmit,
    control,
    setValue,
    formState: { errors },
  } = useForm<DatosPasswordTemporal>({
    resolver: zodResolver(esquema),
    defaultValues: { password_temporal: "", confirmar: "" },
  });
  const password = useWatch({ control, name: "password_temporal" });

  const mutacion = useMutation({
    mutationFn: (d: DatosPasswordTemporal) => usuariosApi.asignarPasswordTemporal(usuario.id, d.password_temporal),
    onSuccess: async () => {
      await invalidar();
      notificar.exito("Contraseña temporal asignada", `${usuario.nombre} deberá cambiarla al ingresar.`);
      alTerminar();
    },
  });

  const generar = () => {
    const clave = generarPasswordTemporal();
    setValue("password_temporal", clave, { shouldValidate: true });
    setValue("confirmar", clave, { shouldValidate: true });
  };

  return (
    <DialogContent
      titulo="Asignar contraseña temporal"
      descripcion={`Para ${usuario.nombre} (${usuario.username}). Se cerrarán sus sesiones abiertas.`}
      pie={
        <>
          <CancelarBtn />
          <Button type="submit" form="form-password-temporal" cargando={mutacion.isPending}>
            Asignar
          </Button>
        </>
      }
    >
      <form id="form-password-temporal" noValidate onSubmit={handleSubmit((d) => mutacion.mutate(d))} className="flex flex-col gap-4">
        {mutacion.isError && <Alert tono="error">{mensajeDeError(mutacion.error)}</Alert>}
        <CamposPasswordTemporal
          registroPassword={register("password_temporal")}
          registroConfirmar={register("confirmar")}
          errorPassword={errors.password_temporal?.message}
          errorConfirmar={errors.confirmar?.message}
          valor={password ?? ""}
          username={usuario.username}
          alGenerar={generar}
        />
      </form>
    </DialogContent>
  );
}
