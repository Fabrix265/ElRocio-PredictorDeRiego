import { zodResolver } from "@hookform/resolvers/zod";
import { KeyRound, LogOut } from "lucide-react";
import { useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useNavigate, useSearchParams } from "react-router";

import { Alert } from "../../../components/ui/Alert";
import { Button } from "../../../components/ui/Button";
import { Card, CardBody } from "../../../components/ui/Card";
import { Field } from "../../../components/ui/Field";
import { PageHeader } from "../../../components/ui/PageHeader";
import { PasswordInput } from "../../../components/ui/PasswordInput";
import { notificar } from "../../../components/ui/Toast";
import { sanearNext } from "../../../lib/next";
import { mensajeDeError } from "../../../services/httpClient";
import { AppLayout } from "../../layout/AppLayout";
import { AuthLayout } from "../AuthLayout";
import { useAuth, useUsuario } from "../AuthProvider";
import { crearEsquemaCambio, type DatosCambio } from "../esquemas";
import { ReglasPassword } from "../ReglasPassword";

function FormCambiarPassword({ obligatorio }: { obligatorio: boolean }) {
  const usuario = useUsuario();
  const { cambiarPassword, cerrarSesion } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const esquema = useMemo(() => crearEsquemaCambio(usuario.username), [usuario.username]);

  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<DatosCambio>({
    resolver: zodResolver(esquema),
    defaultValues: { actual: "", nueva: "", confirmar: "" },
  });
  const nueva = useWatch({ control, name: "nueva" });

  const enviar = handleSubmit(async ({ actual, nueva: clave }) => {
    setError(null);
    try {
      await cambiarPassword(actual, clave);
      notificar.exito("Contraseña actualizada", "Las demás sesiones abiertas se cerraron.");
      reset();
      if (obligatorio) navigate(sanearNext(params.get("next")), { replace: true });
    } catch (e) {
      setError(mensajeDeError(e));
    }
  });

  return (
    <form onSubmit={enviar} noValidate className="flex flex-col gap-4">
      {error && <Alert tono="error">{error}</Alert>}
      <Field label={obligatorio ? "Contraseña temporal" : "Contraseña actual"} error={errors.actual?.message}>
        <PasswordInput autoComplete="current-password" autoFocus={obligatorio} {...register("actual")} />
      </Field>
      <Field label="Nueva contraseña" error={errors.nueva?.message}>
        <PasswordInput autoComplete="new-password" {...register("nueva")} />
      </Field>
      <ReglasPassword password={nueva ?? ""} username={usuario.username} />
      <Field label="Repite la nueva contraseña" error={errors.confirmar?.message}>
        <PasswordInput autoComplete="new-password" {...register("confirmar")} />
      </Field>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <Button type="submit" tamano="lg" cargando={isSubmitting} icono={<KeyRound aria-hidden="true" />} className={obligatorio ? "w-full" : ""}>
          Guardar contraseña
        </Button>
      </div>
      {obligatorio && (
        <Button variante="fantasma" icono={<LogOut aria-hidden="true" />} onClick={() => void cerrarSesion()} className="self-start">
          Cerrar sesión
        </Button>
      )}
    </form>
  );
}

/** Primer ingreso (contraseña temporal, pantalla completa) o cambio voluntario desde el menú. */
export function CambiarPasswordPage() {
  const usuario = useUsuario();

  if (usuario.debe_cambiar_password) {
    return (
      <AuthLayout
        titulo="Crea tu contraseña"
        descripcion={`Hola, ${usuario.nombre.split(" ")[0]}. Ingresaste con una contraseña temporal; por seguridad, crea una nueva para continuar.`}
      >
        <FormCambiarPassword obligatorio />
      </AuthLayout>
    );
  }

  return (
    <AppLayout>
      <div className="flex flex-col gap-4">
        <PageHeader
          antetitulo="Mi cuenta"
          titulo="Cambiar contraseña"
          descripcion="Al guardar, se cerrarán tus sesiones en otros dispositivos."
        />
        <Card className="max-w-xl">
          <CardBody className="pt-4">
            <FormCambiarPassword obligatorio={false} />
          </CardBody>
        </Card>
      </div>
    </AppLayout>
  );
}
