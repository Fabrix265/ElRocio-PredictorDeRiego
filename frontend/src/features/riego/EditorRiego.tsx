import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Checkbox } from "../../components/ui/Checkbox";
import { Field } from "../../components/ui/Field";
import { Input } from "../../components/ui/Input";
import { notificar } from "../../components/ui/Toast";
import { hoyLima } from "../../lib/fechas";
import { claveCronogramas } from "../../services/cronogramas";
import { ApiError, mensajeDeError } from "../../services/httpClient";
import { claveRiego, riegoApi, type CicloRiegoEntrada, type RegistroRiego, type VersionRiego } from "../../services/riego";
import { minutosAHora } from "../cronogramas/etiquetas";

type Modo = "editar" | "sin_riego" | "aplicado";
export function AccionesRiego({ registro, turnoId, fecha, alRecargar }: { registro: RegistroRiego | null; turnoId: number; fecha: string; alRecargar: () => Promise<unknown> }) {
  const [edicion, setEdicion] = useState<{ modo: Modo; base: RegistroRiego | null } | null>(null);
  if (edicion) return <EditorRiego modo={edicion.modo} base={edicion.base} turnoId={turnoId} fecha={fecha} alCerrar={() => setEdicion(null)} alRecargar={alRecargar} />;
  return <div className="flex flex-wrap gap-2">
    <Button onClick={() => setEdicion({ modo: "editar", base: registro })}>Editar riego</Button>
    <Button variante="secundario" onClick={() => setEdicion({ modo: "sin_riego", base: registro })}>No se regó</Button>
    {fecha < hoyLima() && registro?.estado === "provisional" && <Button variante="secundario" onClick={() => setEdicion({ modo: "aplicado", base: registro })}>Marcar aplicado</Button>}
  </div>;
}

function EditorRiego({ modo, base, turnoId, fecha, alCerrar, alRecargar }: {
  modo: Modo; base: RegistroRiego | null; turnoId: number; fecha: string; alCerrar: () => void; alRecargar: () => Promise<unknown>;
}) {
  const qc = useQueryClient();
  const [motivo, setMotivo] = useState("");
  const [comentario, setComentario] = useState("");
  const [ciclos, setCiclos] = useState<CicloRiegoEntrada[]>(() => base?.ciclos.length ? base.ciclos.map((c) => ({ inicio_min: c.inicio_min, duracion_min: c.duracion_min, riego_m3ha: c.riego_m3ha ?? NaN })) : [{ inicio_min: 360, duracion_min: 60, riego_m3ha: 0 }]);
  const sinRiego = modo === "sin_riego" || (modo === "aplicado" && !!base?.sin_riego);
  const guardar = useMutation({
    mutationFn: () => riegoApi.guardarRegistro({ turno_id: turnoId, fecha, basado_en_id: base?.id ?? null, estado: modo === "aplicado" ? "aplicado" : base?.estado ?? "provisional", sin_riego: sinRiego, motivo: motivo.trim(), comentario: comentario.trim() || null, ciclos: sinRiego ? [] : ciclos }),
    onSuccess: async (registro) => {
      qc.setQueryData<VersionRiego[]>(claveRiego.versiones(turnoId, fecha), (anteriores) => [
        { ...registro, vigente: true, basado_en_id: base?.id ?? null },
        ...(anteriores ?? []).map((v) => ({ ...v, vigente: false })),
      ]);
      await Promise.all([qc.invalidateQueries({ queryKey: claveRiego.todo }), qc.invalidateQueries({ queryKey: claveCronogramas.todo })]);
      notificar.exito(modo === "aplicado" ? "Riego marcado como aplicado" : "Se guardó el riego");
      alCerrar();
    },
  });
  const conflicto = guardar.error instanceof ApiError && guardar.error.status === 409;
  const invalidos = !sinRiego && ciclos.some((c) => !Object.values(c).every(Number.isFinite) || c.duracion_min < 0.1 || c.duracion_min > 1440 || c.riego_m3ha < 0.01 || c.riego_m3ha > 100 || c.inicio_min < 0 || c.inicio_min >= 2880);
  function cambiar(i: number, datos: Partial<CicloRiegoEntrada>) { setCiclos((cs) => cs.map((c, j) => i === j ? { ...c, ...datos } : c)); }
  const titulo = { editar: "Editar riego", sin_riego: "No se regó", aplicado: "Marcar aplicado" }[modo];
  return <section className="flex min-w-0 flex-col gap-3" aria-label={titulo}>
    <h3 className="text-sm font-semibold">{titulo}</h3>
    {modo === "aplicado" && <Alert tono="info">Se conservarán los mismos ciclos del riego vigente y se marcarán como aplicados.</Alert>}
    {sinRiego && <Alert tono="info">Se guardará el turno-día sin ciclos de riego.</Alert>}
    {modo === "editar" && <>
      <div className="max-w-full overflow-x-auto rounded-md border border-borde">
        <table className="w-full min-w-[550px] text-sm"><caption className="sr-only">Ciclos de riego editables</caption>
          <thead className="bg-hundido text-left"><tr>{["Ciclo", "Inicio", "Duración (min)", "m³/ha", "Acciones"].map((s) => <th key={s} className="p-2">{s}</th>)}</tr></thead>
          <tbody>{ciclos.map((c, i) => <tr key={i} className="border-t border-borde">
            <th className="p-2" scope="row">{i + 1}</th>
            <td className="p-2"><Input type="time" aria-label={`Inicio del ciclo ${i + 1}`} value={Number.isFinite(c.inicio_min) ? minutosAHora(c.inicio_min) : ""} disabled={guardar.isPending} onChange={(e) => { const [h, m] = e.target.value.split(":").map(Number); cambiar(i, { inicio_min: e.target.value ? h * 60 + m + (c.inicio_min >= 1440 ? 1440 : 0) : NaN }); }} />
              <label className="mt-2 flex items-center gap-2 text-xs"><Checkbox aria-label={`Inicio al día siguiente del ciclo ${i + 1}`} checked={c.inicio_min >= 1440} disabled={guardar.isPending || !Number.isFinite(c.inicio_min)} onChange={(e) => cambiar(i, { inicio_min: c.inicio_min % 1440 + (e.target.checked ? 1440 : 0) })} />Día siguiente</label>
            </td>
            <td className="p-2"><Input type="number" min="0.1" step="0.1" aria-label={`Duración del ciclo ${i + 1}`} disabled={guardar.isPending} value={Number.isFinite(c.duracion_min) ? c.duracion_min : ""} onChange={(e) => cambiar(i, { duracion_min: e.target.valueAsNumber })} /></td>
            <td className="p-2"><Input type="number" min="0.01" step="0.01" aria-label={`m³/ha del ciclo ${i + 1}`} disabled={guardar.isPending} value={Number.isFinite(c.riego_m3ha) ? c.riego_m3ha : ""} onChange={(e) => cambiar(i, { riego_m3ha: e.target.valueAsNumber })} /></td>
            <td className="p-2"><Button variante="fantasma" disabled={guardar.isPending || ciclos.length === 1} aria-label={`Quitar ciclo ${i + 1}`} onClick={() => setCiclos((cs) => cs.filter((_, j) => i !== j))}>Quitar</Button></td>
          </tr>)}</tbody>
        </table>
      </div>
      <Button variante="secundario" className="self-start" disabled={guardar.isPending || ciclos.length >= 5} onClick={() => setCiclos((cs) => [...cs, { inicio_min: Math.min(2879, (cs.at(-1)?.inicio_min ?? 300) + (cs.at(-1)?.duracion_min ?? 60)), duracion_min: 60, riego_m3ha: 0 }])}>Agregar ciclo</Button>
    </>}
    <Field label="Motivo" requerido ayuda={`${motivo.trim().length}/255 caracteres`}><Input maxLength={255} value={motivo} disabled={guardar.isPending} onChange={(e) => setMotivo(e.target.value)} /></Field>
    <Field label="Comentario (opcional)"><Input maxLength={1000} value={comentario} disabled={guardar.isPending} onChange={(e) => setComentario(e.target.value)} /></Field>
    {invalidos && <Alert tono="aviso">Completa la hora, entre 0,1 y 1440 minutos de duración y entre 0,01 y 100 m³/ha en cada ciclo.</Alert>}
    {guardar.isError && <Alert tono="error">{conflicto ? "Otro usuario cambió este riego. Recarga." : mensajeDeError(guardar.error)}{conflicto && <Button variante="secundario" onClick={() => { void alRecargar().then(alCerrar); }}>Recargar</Button>}</Alert>}
    <div className="flex flex-wrap gap-2">
      <Button variante="secundario" disabled={guardar.isPending} onClick={alCerrar}>Cancelar</Button>
      <Button disabled={guardar.isPending || conflicto || invalidos || !motivo.trim()} onClick={() => guardar.mutate()}>{guardar.isPending ? "Guardando…" : modo === "aplicado" ? "Marcar aplicado" : "Guardar riego"}</Button>
    </div>
  </section>;
}
