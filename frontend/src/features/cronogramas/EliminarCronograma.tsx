import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog, DialogContent } from "../../components/ui/Dialog";
import { Field } from "../../components/ui/Field";
import { Input } from "../../components/ui/Input";
import { notificar } from "../../components/ui/Toast";
import { puede } from "../../lib/roles";
import { claveCronogramas, cronogramasApi, type CronogramaDetalle } from "../../services/cronogramas";
import { claveDatos } from "../../services/datos";
import { ApiError, mensajeDeError } from "../../services/httpClient";
import { claveReportes } from "../../services/reportes";
import { claveRiego } from "../../services/riego";
import { useUsuario } from "../auth/AuthProvider";

export function EliminarCronograma({ cronograma, bloqueado }: { cronograma: CronogramaDetalle; bloqueado: boolean }) {
  const usuario = useUsuario();
  const qc = useQueryClient();
  const navegar = useNavigate();
  // Conserva el lock de apertura aunque el detalle se actualice en segundo plano.
  const [base, setBase] = useState<CronogramaDetalle | null>(null);
  const [motivo, setMotivo] = useState("");
  const definitivo = base?.version_publicada_id == null && base?.num_publicaciones === 0;
  const verbo = definitivo ? "Eliminar" : "Anular";
  const eliminar = useMutation({
    mutationFn: () => cronogramasApi.eliminar(base!.id, { motivo: motivo.trim(), lock_version: base!.lock_version }),
    onSuccess: async (r) => {
      // El detalle eliminado no debe volver a pedirse antes de salir (respondería 404).
      await Promise.all([claveCronogramas.todo, claveRiego.todo, claveReportes.todo, claveDatos.todo].map((queryKey) =>
        qc.invalidateQueries({ queryKey, refetchType: "none" }),
      ));
      setBase(null);
      notificar.exito(r.accion === "eliminado" ? "Cronograma eliminado" : "Cronograma anulado", r.avisos.join(" · ") || undefined);
      navegar("/cronogramas");
    },
  });
  const conflicto = eliminar.error instanceof ApiError && eliminar.error.status === 409;
  if (!puede(usuario.rol, "eliminarCronogramas")) return null;
  return <>
    <Button variante="secundario" className="text-err-tx" icono={<Trash2 aria-hidden="true" />} disabled={bloqueado || eliminar.isPending}
      onClick={() => { eliminar.reset(); setMotivo(""); setBase(cronograma); }}>Eliminar</Button>
    <Dialog open={!!base} onOpenChange={(abierto) => { if (!abierto && !eliminar.isPending) setBase(null); }}>
      <DialogContent titulo={`${verbo} cronograma`} descripcion={definitivo
        ? "Se eliminará definitivamente (nunca se publicó)."
        : "Se anulará: deja de verse y la fecha queda libre para generar de nuevo. Sus versiones se guardan para reentrenar el modelo. Se quitan los riegos provisionales que creó; los aplicados y los editados a mano se conservan."}
        pie={<>
          <Button variante="secundario" disabled={eliminar.isPending} onClick={() => setBase(null)}>Cancelar</Button>
          <Button variante="peligro" disabled={eliminar.isPending || conflicto || motivo.trim().length < 3 || motivo.trim().length > 500}
            onClick={() => eliminar.mutate()}>{eliminar.isPending ? "Guardando…" : verbo}</Button>
        </>}>
        <div className="flex flex-col gap-3">
          <Field label="Motivo" requerido ayuda="De 3 a 500 caracteres.">
            <Input value={motivo} maxLength={500} disabled={eliminar.isPending} onChange={(e) => setMotivo(e.target.value)} />
          </Field>
          {eliminar.isError && <Alert tono="error">
            {conflicto ? "Otro usuario modificó el cronograma. Recarga para ver los cambios." : mensajeDeError(eliminar.error)}
            {conflicto && <Button variante="secundario" onClick={() => {
              void qc.invalidateQueries({ queryKey: claveCronogramas.detalle(cronograma.id) }).then(() => setBase(null));
            }}>Recargar</Button>}
          </Alert>}
        </div>
      </DialogContent>
    </Dialog>
  </>;
}
