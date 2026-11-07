import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Mail } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router";

import { Alert } from "../../../components/ui/Alert";
import { Button, clasesBoton } from "../../../components/ui/Button";
import { Field } from "../../../components/ui/Field";
import { Input } from "../../../components/ui/Input";
import { mensajeDeError } from "../../../services/httpClient";
import { authApi } from "../api";
import { AuthLayout } from "../AuthLayout";
import { esquemaRecuperar, type DatosRecuperar } from "../esquemas";

const MENSAJE_ENVIADO = "Si el usuario existe, enviaremos un enlace a su correo.";

export function RecuperarPage() {
  const [enviado, setEnviado] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<DatosRecuperar>({ resolver: zodResolver(esquemaRecuperar), defaultValues: { identificador: "" } });

  const enviar = handleSubmit(async ({ identificador }) => {
    setError(null);
    try {
      const r = await authApi.recuperar(identificador.trim());
      setEnviado(r?.detail || MENSAJE_ENVIADO);
    } catch (e) {
      setError(mensajeDeError(e));
    }
  });

  return (
    <AuthLayout
      titulo="Recuperar contraseña"
      descripcion="Escribe tu usuario o tu correo. Te enviaremos un enlace para crear una contraseña nueva; vence en 30 minutos."
    >
      {enviado ? (
        <div className="flex flex-col gap-4">
          <Alert tono="exito" titulo="Solicitud recibida">
            {enviado} Revisa también la carpeta de correo no deseado.
          </Alert>
          <Link to="/login" className={clasesBoton("secundario", "lg", "w-full")}>
            <ArrowLeft aria-hidden="true" />
            Volver a iniciar sesión
          </Link>
        </div>
      ) : (
        <form onSubmit={enviar} noValidate className="flex flex-col gap-4">
          {error && <Alert tono="error">{error}</Alert>}
          <Field label="Usuario o correo" error={errors.identificador?.message}>
            <Input autoComplete="username" autoCapitalize="none" spellCheck={false} autoFocus {...register("identificador")} />
          </Field>
          <Button type="submit" tamano="lg" cargando={isSubmitting} icono={<Mail aria-hidden="true" />} className="w-full">
            Enviar enlace
          </Button>
          <Link
            to="/login"
            className="inline-flex items-center gap-1.5 self-start rounded text-[13px] font-medium text-activo-tx underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-foco"
          >
            <ArrowLeft className="size-3.5" aria-hidden="true" />
            Volver a iniciar sesión
          </Link>
        </form>
      )}
    </AuthLayout>
  );
}
