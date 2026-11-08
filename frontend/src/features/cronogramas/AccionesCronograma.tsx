import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Dialog, DialogContent } from "../../components/ui/Dialog";
import { Field } from "../../components/ui/Field";
import { Input } from "../../components/ui/Input";
import { notificar } from "../../components/ui/Toast";
import { hoyLima } from "../../lib/fechas";
import { puede } from "../../lib/roles";
import { claveCronogramas, cronogramasApi, type CronogramaDetalle } from "../../services/cronogramas";
import { ApiError, mensajeDeError } from "../../services/httpClient";
import { claveRiego } from "../../services/riego";
import { useUsuario } from "../auth/AuthProvider";

type Accion = "publicar" | "descartar" | "visto" | "solicitar" | "mantener";
interface Confirmacion { accion: Accion; titulo: string; descripcion: string; base: CronogramaDetalle }

export function AccionesCronograma({ cronograma: c, bloqueado }: { cronograma: CronogramaDetalle; bloqueado: boolean }) {
  const usuario = useUsuario();
  const qc = useQueryClient();
  const [dialogo, setDialogo] = useState<Confirmacion | null>(null);
  const [texto, setTexto] = useState("");
  const [avisos, setAvisos] = useState<string[]>([]);
  const [mensaje, setMensaje] = useState<string | null>(null);
  const refrescar = () => qc.invalidateQueries({ queryKey: claveCronogramas.todo });
  const ejecutar = useMutation({
    mutationFn: async ({ accion, base }: Confirmacion) => {
      switch (accion) {
        case "publicar": return cronogramasApi.publicar(base.id, base.lock_version);
        case "descartar": return cronogramasApi.descartarBorrador(base.id);
        case "visto": return cronogramasApi.visto(base.id, base.version_publicada_id!);
        case "solicitar": return cronogramasApi.solicitarCorreccion(base.id, base.version_publicada_id!, texto.trim());
        case "mantener": return cronogramasApi.mantener(base.id, texto.trim());
      }
    },
    onSuccess: async (r, accion) => {
      qc.setQueryData(claveCronogramas.detalle(c.id), r);
      setAvisos("avisos" in r ? r.avisos as string[] : []);
      await Promise.all([refrescar(), qc.invalidateQueries({ queryKey: claveRiego.todo })]);
      setDialogo(null);
      notificar.exito({ publicar: "Cronograma publicado", descartar: "Se descartaron los cambios", visto: "Visto confirmado", solicitar: "Corrección solicitada", mantener: "Se mantuvo la versión" }[accion.accion]);
    },
    onError: (e, accion) => {
      if (e instanceof ApiError && e.status === 409 && accion.accion === "visto") {
        setMensaje("Hay una versión publicada más nueva");
        setDialogo(null);
        void refrescar();
      }
    },
  });
  const abrir = (accion: Accion, titulo: string, descripcion: string) => {
    ejecutar.reset(); setTexto(""); setMensaje(null); setAvisos([]);
    setDialogo({ accion, titulo, descripcion, base: c });
  };
  const publicado = c.estado !== "borrador";
  const acciones: { accion: Accion; titulo: string; descripcion: string; visible: boolean }[] = [
    { accion: "publicar", titulo: publicado ? "Publicar cambios" : "Publicar", visible: puede(usuario.rol, "publicarCronogramas") && !!c.borrador_version_id,
      descripcion: !publicado ? "Se avisará al programador y al subgerente" : c.fecha < hoyLima() ? "Corrección retrospectiva: solo se avisa al subgerente" : "El programador deberá confirmar el Visto de nuevo" },
    { accion: "descartar", titulo: "Descartar cambios", descripcion: "Se conservará la versión publicada. Las versiones anteriores seguirán en el historial.", visible: puede(usuario.rol, "publicarCronogramas") && publicado && !!c.borrador_version_id },
    { accion: "visto", titulo: "Confirmar Visto", descripcion: "Confirma que recibiste y programaste la versión publicada. Se registrará el riego provisional y se avisará al subgerente.", visible: puede(usuario.rol, "confirmarVisto") && c.estado === "publicado" && c.fecha >= hoyLima() && !!c.version_publicada_id },
    { accion: "solicitar", titulo: "Solicitar corrección", descripcion: "Indica el motivo de la solicitud. Se avisará al encargado.", visible: puede(usuario.rol, "solicitarCorreccion") && ["publicado", "visto"].includes(c.estado) && !!c.version_publicada_id },
    { accion: "mantener", titulo: "Mantener versión", descripcion: "Explica por qué se mantiene la versión publicada. Se avisará al subgerente.", visible: puede(usuario.rol, "mantenerCronograma") && c.estado === "correccion_solicitada" },
  ];
  const requiereTexto = dialogo?.accion === "solicitar" || dialogo?.accion === "mantener";
  const conflicto = ejecutar.error instanceof ApiError && ejecutar.error.status === 409;
  return <div className="flex min-w-0 flex-col gap-3">
    <div className="flex flex-wrap gap-2">{acciones.filter((a) => a.visible).map((a) => <Button key={a.accion} variante={a.accion === "descartar" ? "secundario" : "primario"} disabled={bloqueado || ejecutar.isPending} onClick={() => abrir(a.accion, a.titulo, a.descripcion)}>{a.titulo}</Button>)}</div>
    {mensaje && <Alert tono="aviso">{mensaje}</Alert>}
    {avisos.length > 0 && <Alert tono="aviso" titulo="Avisos"><ul className="list-disc pl-4">{avisos.map((a, i) => <li key={i}>{a}</li>)}</ul></Alert>}
    <Dialog open={!!dialogo} onOpenChange={(v) => { if (!v && !ejecutar.isPending) setDialogo(null); }}>
      <DialogContent titulo={dialogo?.titulo} descripcion={dialogo?.descripcion} pie={<>
        <Button variante="secundario" disabled={ejecutar.isPending} onClick={() => setDialogo(null)}>Cancelar</Button>
        <Button disabled={ejecutar.isPending || conflicto || (requiereTexto && (texto.trim().length < 5 || texto.trim().length > 1000))} onClick={() => dialogo && ejecutar.mutate(dialogo)}>{ejecutar.isPending ? "Guardando…" : dialogo?.titulo}</Button>
      </>}>
        <div className="flex flex-col gap-3">
          <p className="text-sm text-texto-2">Versión {dialogo?.accion === "publicar" ? `v${dialogo.base.version?.numero}` : `v${dialogo?.base.versiones.find((v) => v.id === dialogo.base.version_publicada_id)?.numero ?? "—"}`}</p>
          {requiereTexto && <Field label={dialogo?.accion === "solicitar" ? "Motivo" : "Comentario"} requerido ayuda={`${texto.trim().length}/1000 caracteres · mínimo 5`}><Input value={texto} maxLength={1000} disabled={ejecutar.isPending} onChange={(e) => setTexto(e.target.value)} /></Field>}
          {ejecutar.isError && <Alert tono="error">{conflicto ? "Otro usuario modificó el cronograma. Recarga para ver los cambios." : mensajeDeError(ejecutar.error)}{conflicto && <Button variante="secundario" onClick={() => { void refrescar().then(() => setDialogo(null)); }}>Recargar</Button>}</Alert>}
        </div>
      </DialogContent>
    </Dialog>
  </div>;
}
