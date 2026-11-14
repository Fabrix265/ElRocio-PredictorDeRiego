import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";
import { Checkbox } from "../../components/ui/Checkbox";
import { Dialog, DialogContent } from "../../components/ui/Dialog";
import { Field } from "../../components/ui/Field";
import { Input } from "../../components/ui/Input";
import { Select } from "../../components/ui/Select";
import { Skeleton } from "../../components/ui/Skeleton";
import { notificar } from "../../components/ui/Toast";
import { cn } from "../../lib/cn";
import { claveCronogramas, cronogramasApi, type CicloCronograma, type CronogramaDetalle, type TurnoCronograma } from "../../services/cronogramas";
import { ApiError, mensajeDeError } from "../../services/httpClient";
import { minutosAHora } from "./etiquetas";
import { calcular, ordenarEnFila, solapesEntreTurnos } from "./fila";

const entradaCiclo = (c: CicloCronograma) => ({ ciclo: c.ciclo, riego_m3ha: c.riego_m3ha, inicio_min: c.inicio_min, duracion_min: c.duracion_min, duracion_manual: c.duracion_manual });
const entradaTurno = (t: TurnoCronograma) => ({ turno_id: t.turno_id, n_ciclos: t.n_ciclos, ciclos: t.ciclos.map(entradaCiclo) });

/** N.º de ciclos que se pueden elegir: los que trae el backend (1–5 del modelo o 1–12 con riego
 * por pulsos) con la lista completa, más el actual. */
export function opcionesN(alternativas: Record<string, unknown[]> | undefined, actual: number): number[] {
  const disponibles = Object.entries(alternativas ?? {})
    .filter(([n, ciclos]) => Number.isInteger(Number(n)) && ciclos.length === Number(n))
    .map(([n]) => Number(n));
  return [...new Set([...disponibles, actual])].sort((a, b) => a - b);
}

function tieneSolapes(t: TurnoCronograma) {
  const orden = [...t.ciclos].sort((a, b) => a.inicio_min - b.inicio_min);
  return orden.some((c, i) => i > 0 && c.inicio_min < orden[i - 1].fin_min);
}

/** Se monta con una foto de la base y del lock: los refetch no reemplazan una edición en curso. */
export function EditorPlan({ cronograma, alCerrar, alRecargar }: { cronograma: CronogramaDetalle; alCerrar: () => void; alRecargar: () => Promise<unknown> }) {
  const [base] = useState(cronograma);
  const porPulsos = !!base.version!.calculo_pulsos;
  const inicioMin = Math.min(...base.version!.turnos.flatMap((t) => t.ciclos.map((c) => c.inicio_min)));
  const [turnos, setTurnos] = useState(() => structuredClone(base.version!.turnos));
  const [dialogo, setDialogo] = useState<"guardar" | "cancelar" | null>(null);
  const [motivo, setMotivo] = useState("");
  const [comentario, setComentario] = useState("");
  const queryClient = useQueryClient();
  const basadaEn = base.borrador_version_id ?? base.version_publicada_id!;
  const alternativas = useQuery({
    queryKey: claveCronogramas.alternativas(base.id, basadaEn),
    queryFn: () => cronogramasApi.alternativas(base.id),
    staleTime: Infinity, refetchOnMount: "always", refetchOnWindowFocus: false, refetchOnReconnect: false, retry: false,
  });
  const motivos = useQuery({ queryKey: claveCronogramas.motivos, queryFn: ({ signal }) => cronogramasApi.motivos(signal), enabled: dialogo === "guardar" });
  const editados = turnos.filter((t) => JSON.stringify(entradaTurno(t)) !== JSON.stringify(entradaTurno(base.version!.turnos.find((b) => b.turno_id === t.turno_id)!)));
  const invalidos = editados.some((t) => t.ciclos.some((c) => {
    const anterior = base.version!.turnos.find((b) => b.turno_id === t.turno_id)?.ciclos.find((b) => b.ciclo === c.ciclo);
    const cambiado = !anterior || JSON.stringify(entradaCiclo(c)) !== JSON.stringify(entradaCiclo(anterior));
    return ![c.riego_m3ha, c.inicio_min, c.duracion_min].every(Number.isFinite)
      || c.riego_m3ha <= 0 || c.riego_m3ha > 100 || c.duracion_min <= 0 || c.duracion_min > 1440
      || c.inicio_min < 0 || c.inicio_min >= 2880
      || (cambiado && !c.duracion_manual && !(t.factor_min_por_m3ha && t.factor_min_por_m3ha > 0));
  }));
  const guardar = useMutation({
    mutationFn: () => cronogramasApi.guardarVersion(base.id, { basada_en_id: basadaEn, lock_version: base.lock_version, turnos: editados.map(entradaTurno), motivo_codigo: motivo, motivo_comentario: comentario.trim() || null }),
    onSuccess: async (r) => {
      queryClient.setQueryData(claveCronogramas.detalle(base.id), r);
      await queryClient.invalidateQueries({ queryKey: claveCronogramas.todo });
      notificar.exito(`Se guardó la versión v${r.version?.numero}`);
      alCerrar();
    },
  });
  const conflicto = guardar.error instanceof ApiError && guardar.error.status === 409;
  function ordenarSiPulsos(ts: TurnoCronograma[]) {
    // Mientras se vacía un campo numérico, no propagar NaN a los horarios de otros turnos.
    return porPulsos && ts.every((t) => t.ciclos.every((c) => Number.isFinite(c.duracion_min) && c.duracion_min > 0))
      ? ordenarEnFila(ts, inicioMin) : ts;
  }
  function cambiar(turnoId: number, ciclo: number, valores: Partial<CicloCronograma>) {
    setTurnos((ts) => {
      const nuevos = ts.map((t) => t.turno_id !== turnoId ? t : { ...t, ciclos: t.ciclos.map((c) => c.ciclo === ciclo ? calcular({ ...c, ...valores }, t) : c) });
      return "inicio_min" in valores ? nuevos : ordenarSiPulsos(nuevos);
    });
  }
  function ajustar() {
    setTurnos((ts) => ts.map((t) => {
      let fin = 0;
      const ciclos = [...t.ciclos].sort((a, b) => a.inicio_min - b.inicio_min).map((c) => {
        const nuevo = c.inicio_min < fin ? calcular({ ...c, inicio_min: fin }, t) : c;
        fin = nuevo.fin_min;
        return nuevo;
      }).sort((a, b) => a.ciclo - b.ciclo);
      return { ...t, ciclos };
    }));
  }
  const solapes = turnos.some(tieneSolapes);
  const solapesTurnos = porPulsos ? solapesEntreTurnos(turnos) : [];
  return (
    <div className="flex min-w-0 flex-col gap-4 p-4">
      <p className="text-sm text-texto-2">Corrigiendo v{base.version!.numero}. Las celdas modificadas se resaltan en verde.</p>
      {alternativas.isPending ? <Skeleton className="h-10" /> : alternativas.isError ? <Alert tono="error">No se pudieron cargar las alternativas: {mensajeDeError(alternativas.error)} <Button variante="fantasma" onClick={() => void alternativas.refetch()} disabled={alternativas.isFetching}>Reintentar</Button></Alert> : Object.keys(alternativas.data).length === 0 && <Alert tono="info">Sin alternativas del modelo. Puedes corregir los ciclos existentes.</Alert>}
      {solapes && <Alert tono="aviso">Hay ciclos que se solapan en un mismo turno. Puedes guardar o usar «Ajustar solapes».</Alert>}
      {solapes && <Button className="self-start" variante="secundario" onClick={ajustar} disabled={guardar.isPending}>Ajustar solapes</Button>}
      {solapesTurnos.length > 0 && <Alert tono="aviso">Hay turnos que riegan al mismo tiempo: {solapesTurnos.slice(0, 3).map(({ a, b }) => `${a} y ${b}`).join("; ")}{solapesTurnos.length > 3 ? "…" : "."} Usa «Ordenar en fila».</Alert>}
      {porPulsos && <Button className="self-start" variante="secundario" onClick={() => setTurnos(ordenarSiPulsos)} disabled={guardar.isPending}>Ordenar en fila</Button>}
      {turnos.map((t) => {
        const original = base.version!.turnos.find((b) => b.turno_id === t.turno_id)!;
        return <section key={t.turno_id} className="min-w-0 rounded-lg border border-borde">
          <div className="flex flex-wrap items-center gap-3 p-3">
            <h3 className="font-semibold">{t.turno_codigo}</h3>
            <Field label="N.º de ciclos" className={cn("w-36 rounded-md", t.n_ciclos !== original.n_ciclos && "bg-activo-bg")}>
              <Select value={String(t.n_ciclos)} disabled={guardar.isPending || !alternativas.data?.[t.turno_id]} opciones={opcionesN(alternativas.data?.[t.turno_id], t.n_ciclos).map((n) => ({ value: String(n), label: String(n) }))} onValueChange={(n) => {
                const ciclos = alternativas.data?.[t.turno_id]?.[n];
                if (ciclos) setTurnos((ts) => ordenarSiPulsos(ts.map((x) => x.turno_id !== t.turno_id ? x : { ...x, n_ciclos: Number(n), ciclos: ciclos.map((c) => calcular({ ...c, ciclo_modelo: null, duracion_manual: !(t.factor_min_por_m3ha && t.factor_min_por_m3ha > 0), campos_editados: [] }, t)) })));
              }} />
            </Field>
            <span className="text-xs text-texto-2">{t.area_ha.toFixed(2)} ha · {t.ciclos.reduce((s, c) => s + c.riego_m3, 0).toFixed(1)} m³</span>
          </div>
          {!(t.factor_min_por_m3ha && t.factor_min_por_m3ha > 0) && <div className="px-3 pb-3"><Alert tono="aviso">Sin factor de duración: marca «Duración manual» en los ciclos que edites.</Alert></div>}
          <div className="max-w-full overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <caption className="sr-only">Edición de ciclos de {t.turno_codigo}</caption>
              <thead className="bg-hundido text-left text-xs text-texto-2"><tr>{["Ciclo", "m³/ha", "Duración (min)", "Inicio", "Fin", "m³"].map((s) => <th key={s} scope="col" className="p-2">{s}</th>)}</tr></thead>
              <tbody>{t.ciclos.map((c) => {
                const b = original.ciclos.find((x) => x.ciclo === c.ciclo);
                const celda = (campo: keyof CicloCronograma) => cn("p-2 align-top", c[campo] !== b?.[campo] && "bg-activo-bg");
                const etiqueta = `${t.turno_codigo}, ciclo ${c.ciclo}`;
                return <tr key={c.ciclo} className="border-t border-borde">
                  <th scope="row" className="p-2">{c.ciclo}</th>
                  <td className={celda("riego_m3ha")}><Input aria-label={`m³/ha de ${etiqueta}`} type="number" min="0.01" step="0.01" value={Number.isFinite(c.riego_m3ha) ? c.riego_m3ha : ""} disabled={guardar.isPending} onChange={(e) => cambiar(t.turno_id, c.ciclo, { riego_m3ha: e.target.valueAsNumber })} /></td>
                  <td className={cn(celda("duracion_min"), c.duracion_manual !== b?.duracion_manual && "bg-activo-bg")}>
                    <Input aria-label={`Duración de ${etiqueta}`} type="number" min="0.1" step="0.1" readOnly={!c.duracion_manual} disabled={guardar.isPending} value={Number.isFinite(c.duracion_min) ? c.duracion_min : ""} onChange={(e) => cambiar(t.turno_id, c.ciclo, { duracion_min: e.target.valueAsNumber })} />
                    <label className="mt-2 flex items-center gap-2 text-xs"><Checkbox aria-label={`Duración manual de ${etiqueta}`} checked={c.duracion_manual} disabled={guardar.isPending} onChange={(e) => cambiar(t.turno_id, c.ciclo, { duracion_manual: e.target.checked })} />Duración manual</label>
                  </td>
                  <td className={celda("inicio_min")}>
                    <Input aria-label={`Inicio de ${etiqueta}`} type="time" value={Number.isFinite(c.inicio_min) ? minutosAHora(c.inicio_min) : ""} disabled={guardar.isPending} onChange={(e) => { const [h, m] = e.target.value.split(":").map(Number); cambiar(t.turno_id, c.ciclo, { inicio_min: e.target.value ? h * 60 + m + (c.inicio_min >= 1440 ? 1440 : 0) : NaN }); }} />
                    <label className="mt-2 flex items-center gap-2 text-xs"><Checkbox aria-label={`Inicio al día siguiente de ${etiqueta}`} checked={c.inicio_min >= 1440} disabled={guardar.isPending || !Number.isFinite(c.inicio_min)} onChange={(e) => cambiar(t.turno_id, c.ciclo, { inicio_min: c.inicio_min % 1440 + (e.target.checked ? 1440 : 0) })} />Día siguiente</label>
                  </td>
                  <td className={celda("fin_min")}>{c.hora_fin}{c.fin_dia_siguiente && " (+1 día)"}</td>
                  <td className={celda("riego_m3")}>{Number.isFinite(c.riego_m3) ? c.riego_m3.toFixed(1) : "—"}</td>
                </tr>;
              })}</tbody>
            </table>
          </div>
        </section>;
      })}
      {invalidos && <Alert tono="aviso">Usa entre 0,01 y 100 m³/ha, entre 0,1 y 1440 minutos e inicio antes de las 48 horas. Sin factor, indica duración manual.</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button variante="secundario" disabled={guardar.isPending} onClick={() => editados.length ? setDialogo("cancelar") : alCerrar()}>Cancelar</Button>
        <Button disabled={!editados.length || invalidos || guardar.isPending} onClick={() => setDialogo("guardar")}>Guardar corrección</Button>
      </div>
      <Dialog open={dialogo !== null} onOpenChange={(abierto) => { if (!abierto && !guardar.isPending) setDialogo(null); }}>
        <DialogContent titulo={dialogo === "cancelar" ? "¿Descartar la corrección sin guardar?" : "Guardar corrección"} pie={<>
          <Button variante="secundario" disabled={guardar.isPending} onClick={() => setDialogo(null)}>Volver</Button>
          {dialogo === "cancelar" ? <Button onClick={alCerrar}>Descartar corrección</Button> : <Button disabled={!motivo || guardar.isPending || conflicto || !motivos.data?.some((m) => m.codigo === motivo)} onClick={() => guardar.mutate()}>{guardar.isPending ? "Guardando…" : "Guardar corrección"}</Button>}
        </>}>
          {dialogo === "cancelar" ? <p>Se perderán los cambios de esta edición.</p> : <div className="flex flex-col gap-3">
            {motivos.isPending ? <Skeleton className="h-10" /> : motivos.isError ? <Alert tono="error">{mensajeDeError(motivos.error)} <Button variante="fantasma" disabled={motivos.isFetching} onClick={() => void motivos.refetch()}>Reintentar</Button></Alert> : !motivos.data?.length ? <Alert tono="aviso">No hay motivos de corrección disponibles.</Alert> : <Field label="Motivo" requerido><Select value={motivo} onValueChange={setMotivo} disabled={guardar.isPending} opciones={[...motivos.data].sort((a, b) => a.orden - b.orden).map((m) => ({ value: m.codigo, label: m.nombre }))} /></Field>}
            <Field label="Comentario (opcional)"><Input maxLength={1000} value={comentario} disabled={guardar.isPending} onChange={(e) => setComentario(e.target.value)} /></Field>
            {guardar.isError && <Alert tono="error">{conflicto ? "Otro usuario modificó el cronograma. Recarga para ver los cambios." : mensajeDeError(guardar.error)}{conflicto && <Button variante="secundario" onClick={() => { void alRecargar().then(alCerrar); }}>Recargar</Button>}</Alert>}
          </div>}
        </DialogContent>
      </Dialog>
    </div>
  );
}
