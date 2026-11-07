import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router";

import type { Rol } from "../../lib/roles";
import { NoAutorizadoPage } from "../../pages/NoAutorizadoPage";
import { PantallaCarga } from "../../pages/PantallaCarga";
import { decidirAcceso } from "./acceso";
import { useAuth } from "./AuthProvider";
import { PantallaSinConexion } from "./PantallasAcceso";

interface RutaProtegidaProps {
  roles?: readonly Rol[];
  children?: ReactNode;
}

export function RutaProtegida({ roles, children }: RutaProtegidaProps) {
  const { estado, usuario, salidaVoluntaria } = useAuth();
  const location = useLocation();
  const decision = decidirAcceso({
    estado,
    usuario,
    roles,
    ruta: location.pathname + location.search,
    salidaVoluntaria,
  });

  switch (decision.tipo) {
    case "cargando":
      return <PantallaCarga />;
    case "sin_conexion":
      return <PantallaSinConexion />;
    case "redirigir":
      return <Navigate to={decision.a} replace />;
    case "prohibido":
      return <NoAutorizadoPage />;
    case "permitido":
      return children ?? <Outlet />;
  }
}
