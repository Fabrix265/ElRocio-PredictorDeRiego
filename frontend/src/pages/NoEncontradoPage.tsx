import { MapPinOff } from "lucide-react";
import { Link } from "react-router";

import { clasesBoton } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";

export function NoEncontradoPage() {
  return (
    <Card>
      <EmptyState
        icono={<MapPinOff />}
        titulo="Página no encontrada"
        descripcion="La dirección no existe o cambió. Revisa el enlace o vuelve al inicio."
        accion={
          <Link to="/" className={clasesBoton("secundario")}>
            Ir al inicio
          </Link>
        }
      />
      <p className="sr-only">Error 404</p>
    </Card>
  );
}
