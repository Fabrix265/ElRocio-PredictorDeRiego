import { zodResolver } from "@hookform/resolvers/zod";
import { LogIn } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";

import { Alert } from "../../../components/ui/Alert";
import { Button } from "../../../components/ui/Button";
import { Field } from "../../../components/ui/Field";
import { Input } from "../../../components/ui/Input";
import { PasswordInput } from "../../../components/ui/PasswordInput";
import { sanearNext } from "../../../lib/next";
import { mensajeDeError } from "../../../services/httpClient";
import { PantallaCarga } from "../../../pages/PantallaCarga";
import { RUTA_CAMBIAR_PASSWORD } from "../acceso";
import { AuthLayout } from "../AuthLayout";
import { useAuth } from "../AuthProvider";
import { esquemaLogin, type DatosLogin } from "../esquemas";

function rutaTrasIngreso(next: string, debeCambiar: boolean): string {
  if (!debeCambiar) return next;
  return next === "/" ? RUTA_CAMBIAR_PASSWORD : `${RUTA_CAMBIAR_PASSWORD}?next=${encodeURIComponent(next)}`;
}

export function LoginPage() {
  const { estado, usuario, iniciarSesion } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const next = sanearNext(params.get("next"));
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<DatosLogin>({ resolver: zodResolver(esquemaLogin), defaultValues: { username: "", password: "" } });

  if (estado === "cargando") return <PantallaCarga />;
  if (estado === "autenticado" && usuario && !isSubmitting) {
    return <Navigate to={rutaTrasIngreso(next, usuario.debe_cambiar_password)} replace />;
  }

  const enviar = handleSubmit(async ({ username, password }) => {
    setError(null);
    try {
      const u = await iniciarSesion(username.trim(), password);
      navigate(rutaTrasIngreso(next, u.debe_cambiar_password), { replace: true });
    } catch (e) {
      setError(mensajeDeError(e));
    }
  });

  return (
    <AuthLayout titulo="Iniciar sesión" descripcion="Ingresa con el usuario que te asignó el administrador.">
      <form onSubmit={enviar} noValidate className="flex flex-col gap-4">
        {error && <Alert tono="error">{error}</Alert>}
        <Field label="Usuario" error={errors.username?.message}>
          <Input autoComplete="username" autoCapitalize="none" spellCheck={false} autoFocus {...register("username")} />
        </Field>
        <Field label="Contraseña" error={errors.password?.message}>
          <PasswordInput autoComplete="current-password" {...register("password")} />
        </Field>
        <Button type="submit" tamano="lg" cargando={isSubmitting} icono={<LogIn aria-hidden="true" />} className="mt-1 w-full">
          Ingresar
        </Button>
        <Link
          to="/recuperar"
          className="self-start rounded text-[13px] font-medium text-activo-tx underline-offset-2 hover:underline focus-visible:outline-2 focus-visible:outline-foco"
        >
          ¿Olvidaste tu contraseña?
        </Link>
      </form>
    </AuthLayout>
  );
}
