import { ShieldX } from "lucide-react";
import { Link } from "react-router";

import { clasesBoton } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";

export function NoAutorizadoPage() {
  return (
    <Card>
      <EmptyState
        icono={<ShieldX />}
        titulo="No tienes acceso a esta sección"
        descripcion="Tu rol no tiene permiso para ver esta pantalla. Si crees que es un error, pide al administrador que revise tu rol."
        accion={
          <Link to="/" className={clasesBoton("secundario")}>
            Ir al inicio
          </Link>
        }
      />
      <p className="sr-only">Error 403</p>
    </Card>
  );
}
