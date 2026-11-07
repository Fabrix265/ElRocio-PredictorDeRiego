import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, KeyRound, LogIn } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { Link } from "react-router";

import { Alert } from "../../../components/ui/Alert";
import { Button, clasesBoton } from "../../../components/ui/Button";
import { Field } from "../../../components/ui/Field";
import { PasswordInput } from "../../../components/ui/PasswordInput";
import { mensajeDeError } from "../../../services/httpClient";
import { authApi } from "../api";
import { AuthLayout } from "../AuthLayout";
import { esquemaRestablecer, type DatosRestablecer } from "../esquemas";
import { extraerTokenFragmento, limpiarFragmento } from "../fragmento";
import { ReglasPassword } from "../ReglasPassword";

const ENLACE_INVALIDO = "El enlace no es válido o ya venció.";

export function RestablecerPage() {
  // El token se lee una sola vez del fragmento y luego se borra de la barra de direcciones.
  const [token] = useState(() => extraerTokenFragmento(window.location.hash));
  const [listo, setListo] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    limpiarFragmento();
  }, []);

  const {
    register,
    handleSubmit,
    control,
    formState: { errors, isSubmitting },
  } = useForm<DatosRestablecer>({
    resolver: zodResolver(esquemaRestablecer),
    defaultValues: { password: "", confirmar: "" },
  });
  const password = useWatch({ control, name: "password" });

  const enviar = handleSubmit(async ({ password: nueva }) => {
    if (!token) return;
    setError(null);
    try {
      await authApi.restablecer(token, nueva);
      setListo(true);
    } catch (e) {
      setError(mensajeDeError(e));
    }
  });

  const enlaceNuevo = (
    <Link to="/recuperar" className={clasesBoton("secundario", "lg", "w-full")}>
      Solicitar un enlace nuevo
    </Link>
  );

  if (!token) {
    return (
      <AuthLayout titulo="Restablecer contraseña">
        <Alert tono="error">{ENLACE_INVALIDO} Solicita uno nuevo desde “¿Olvidaste tu contraseña?”.</Alert>
        {enlaceNuevo}
      </AuthLayout>
    );
  }

  if (listo) {
    return (
      <AuthLayout titulo="Contraseña actualizada">
        <Alert tono="exito">Tu contraseña se cambió y se cerraron las sesiones abiertas. Ya puedes ingresar.</Alert>
        <Link to="/login" className={clasesBoton("primario", "lg", "w-full")}>
          <LogIn aria-hidden="true" />
          Iniciar sesión
        </Link>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout titulo="Crea una contraseña nueva" descripcion="El enlace es de un solo uso. Al guardar se cerrarán tus sesiones abiertas.">
      <form onSubmit={enviar} noValidate className="flex flex-col gap-4">
        {error && (
          <Alert tono="error">
            {error}
            {error === ENLACE_INVALIDO && (
              <>
                {" "}
                <Link to="/recuperar" className="font-semibold underline">
                  Solicita uno nuevo
                </Link>
                .
              </>
            )}
          </Alert>
        )}
        <Field label="Nueva contraseña" error={errors.password?.message}>
          <PasswordInput autoComplete="new-password" autoFocus {...register("password")} />
        </Field>
        <ReglasPassword password={password ?? ""} />
        <Field label="Repite la nueva contraseña" error={errors.confirmar?.message}>
          <PasswordInput autoComplete="new-password" {...register("confirmar")} />
        </Field>
        <Button type="submit" tamano="lg" cargando={isSubmitting} icono={<KeyRound aria-hidden="true" />} className="w-full">
          Guardar contraseña
        </Button>
        <Link
          to="/login"
          className="inline-flex items-center gap-1.5 self-start rounded text-[13px] font-medium text-activo-tx underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-foco"
        >
          <ArrowLeft className="size-3.5" aria-hidden="true" />
          Volver a iniciar sesión
        </Link>
      </form>
    </AuthLayout>
  );
}
