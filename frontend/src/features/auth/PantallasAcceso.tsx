import { RefreshCw } from "lucide-react";

import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Skeleton } from "../../components/ui/Skeleton";
import { MENSAJE_SIN_CONEXION } from "../../services/httpClient";
import { AuthLayout } from "./AuthLayout";
import { useAuth } from "./AuthProvider";

/**
 * Esqueleto de las pantallas de acceso mientras se verifica la sesión: el panel verde y una
 * tarjeta de formulario (no el layout interno de la app, que no corresponde a un usuario sin sesión).
 */
export function PantallaCargaAcceso() {
  return (
    <AuthLayout titulo="Iniciar sesión" descripcion="Verificando tu sesión…">
      <div className="flex flex-col gap-4" role="status" aria-live="polite" aria-busy="true">
        <span className="sr-only">Cargando…</span>
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-3.5 w-16" />
          <Skeleton className="h-10 w-full" />
        </div>
        <div className="flex flex-col gap-1.5">
          <Skeleton className="h-3.5 w-24" />
          <Skeleton className="h-10 w-full" />
        </div>
        <Skeleton className="mt-1 h-10 w-full" />
        <Skeleton className="h-3.5 w-40" />
      </div>
    </AuthLayout>
  );
}

/**
 * El refresh inicial falló por red, timeout o error del servidor: no se sabe si hay sesión,
 * así que no se manda al login (la cookie puede seguir vigente).
 */
export function PantallaSinConexion() {
  const { reintentarConexion } = useAuth();
  return (
    <AuthLayout titulo="No se pudo conectar" descripcion="No pudimos verificar tu sesión con el servidor.">
      <div className="flex flex-col gap-4">
        <Alert tono="aviso" titulo="Sin conexión con el servidor">
          {MENSAJE_SIN_CONEXION} Si tenías una sesión abierta, se recuperará al reconectar.
        </Alert>
        <Button
          tamano="lg"
          autoFocus
          icono={<RefreshCw aria-hidden="true" />}
          className="w-full"
          onClick={reintentarConexion}
        >
          Reintentar
        </Button>
      </div>
    </AuthLayout>
  );
}
