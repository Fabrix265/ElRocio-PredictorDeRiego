import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SlidersHorizontal } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { Checkbox } from "../../components/ui/Checkbox";
import { EmptyState } from "../../components/ui/EmptyState";
import { Field } from "../../components/ui/Field";
import { Input } from "../../components/ui/Input";
import { PageHeader } from "../../components/ui/PageHeader";
import { Select } from "../../components/ui/Select";
import { Skeleton } from "../../components/ui/Skeleton";
import { notificar } from "../../components/ui/Toast";
import { cn } from "../../lib/cn";
import { formatearFechaHora } from "../../lib/fechas";
import { puede } from "../../lib/roles";
import { mensajeDeError } from "../../services/httpClient";
import { clavePulsos, pulsosApi, type DerivadosPulsos, type ParametrosPulsos } from "../../services/pulsos";
import { useUsuario } from "../auth/AuthProvider";
import { useSeleccion } from "../catalogo/SeleccionProvider";
import {
  CAMPOS_SISTEMA, CAMPOS_SUELO, CAMPOS_VENTANA, CURVAS, HORAS, MODOS,
  aEntrada, aFormulario, sumaCurva, type CampoNumero, type Formulario,
} from "./formulario";

const num = (x: number, d = 2) => x.toLocaleString("es-PE", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (x: number) => `${(x * 100).toLocaleString("es-PE", { maximumFractionDigits: 2 })} %`;

export default function ParametrosPulsosPage() {
  const { modulo } = useSeleccion();
  const consulta = useQuery({
    queryKey: clavePulsos.parametros(modulo?.id ?? 0),
    queryFn: ({ signal }) => pulsosApi.obtener(modulo!.id, signal),
    enabled: !!modulo,
  });
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        antetitulo={modulo ? `Riego por pulsos · ${modulo.codigo}` : "Riego por pulsos"}
        titulo="Parámetros de riego"
        descripcion="El modelo da los m³/ha de cada turno; con estos datos el sistema los reparte en pulsos y arma el horario."
      />
      {!modulo ? (
        <EmptyState icono={<SlidersHorizontal />} titulo="Elige un módulo" />
      ) : consulta.isPending ? (
        <Skeleton className="h-96" />
      ) : consulta.isError ? (
        <Alert tono="error" titulo="No se pudieron cargar los parámetros">{mensajeDeError(consulta.error)}</Alert>
      ) : (
        <Editor key={`${consulta.data.modulo_id}-${consulta.data.actualizado_at}`} parametros={consulta.data} />
      )}
    </div>
  );
}

function CampoNum({ campo, f, setF, deshabilitado }: { campo: CampoNumero; f: Formulario; setF: (g: (f: Formulario) => Formulario) => void; deshabilitado: boolean }) {
  return (
    <Field label={`${campo.etiqueta}${campo.unidad ? ` (${campo.unidad})` : ""}`} ayuda={campo.ayuda}>
      <Input
        inputMode="decimal"
        value={f.numeros[campo.clave] ?? ""}
        disabled={deshabilitado}
        placeholder={campo.opcional ? "—" : undefined}
        onChange={(e) => {
          const valor = e.target.value;
          setF((x) => ({ ...x, numeros: { ...x.numeros, [campo.clave]: valor } }));
        }}
      />
    </Field>
  );
}

function Derivados({ d, avisos }: { d: DerivadosPulsos | null; avisos: string[] }) {
  if (!d) return <Alert tono="aviso">{avisos.join(". ") || "Sin cálculo"}</Alert>;
  const filas: [string, string][] = [
    ["Volumen de suelo explorado", `${num(d.volumen_explorado_m3ha, 1)} m³/ha`],
    ["Agua disponible (AD)", `${num(d.agua_disponible_m3ha)} m³/ha`],
    ["Capacidad de riego (CR)", `${num(d.capacidad_riego_m3hah)} m³/ha/h`],
    ["Ancho mojado por los bulbos", `${num(d.ancho_bulbos_m)} m${d.franja_continua ? " · franja continua" : " · bulbos separados"}`],
    ["Intensidad de aplicación", `${num(d.intensidad_mmh, 1)} mm/h`],
    ["Plantas / goteros por ha", `${num(d.plantas_ha, 0)} / ${num(d.goteros_ha, 0)}`],
    ["Agotamiento de la fase", pct(d.agotamiento_fase)],
    [`Agotamiento máx. en 3 h (${d.turnos} turnos)`, pct(d.agotamiento_max_bloque)],
    ["Agotamiento usado por pulso", pct(d.agotamiento_operativo)],
    ["Amortiguación del suelo", `${num(d.amortiguacion_m3ha)} m³/ha`],
    ["Pulso base", `${num(d.volumen_pulso_m3ha)} m³/ha · ${num(d.minutos_pulso, 1)} min`],
  ];
  return (
    <div className="flex flex-col gap-3">
      <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm min-[480px]:grid-cols-2">
        {filas.map(([k, v]) => (
          <div key={k} className="flex justify-between gap-3 border-b border-borde pb-1.5">
            <dt className="text-texto-2">{k}</dt>
            <dd className="text-right font-semibold tabular-nums text-texto">{v}</dd>
          </div>
        ))}
      </dl>
      {avisos.map((a) => <Alert key={a} tono="aviso">{a}</Alert>)}
    </div>
  );
}

function Editor({ parametros }: { parametros: ParametrosPulsos }) {
  const usuario = useUsuario();
  const queryClient = useQueryClient();
  const editable = puede(usuario.rol, "editarParametrosRiego");
  const [f, setF] = useState<Formulario>(() => aFormulario(parametros));
  const [errores, setErrores] = useState<string[]>([]);
  const guardar = useMutation({
    mutationFn: (datos: Parameters<typeof pulsosApi.guardar>[1]) => pulsosApi.guardar(parametros.modulo_id, datos),
    onSuccess: (r) => {
      queryClient.setQueryData(clavePulsos.parametros(r.modulo_id), r);
      notificar.exito("Parámetros guardados", "Se usarán al generar o regenerar cronogramas.");
    },
  });
  const deshabilitado = !editable || guardar.isPending;

  const enviar = (e: FormEvent) => {
    e.preventDefault();
    const { datos, errores } = aEntrada(f);
    setErrores(errores);
    if (datos) guardar.mutate(datos);
  };

  return (
    <form className="flex flex-col gap-4" onSubmit={enviar} noValidate>
      <Card>
        <CardHeader
          titulo="Uso en los cronogramas"
          descripcion={parametros.guardado && parametros.actualizado_at
            ? `Actualizado ${formatearFechaHora(parametros.actualizado_at)}${parametros.actualizado_por ? ` · ${parametros.actualizado_por}` : ""}`
            : "Valores de la planilla (aún sin guardar)"}
          acciones={<Badge tono={f.activo ? "exito" : "neutro"}>{f.activo ? "Riego por pulsos activo" : "Plan directo del modelo"}</Badge>}
        />
        <div className="flex flex-col gap-3 p-4">
          <label className="flex items-start gap-2 text-sm text-texto">
            <Checkbox className="mt-0.5" checked={f.activo} disabled={deshabilitado} onChange={(e) => setF((x) => ({ ...x, activo: e.target.checked }))} />
            <span>
              Repartir los m³/ha del modelo en pulsos
              <span className="block text-xs text-texto-2">Si se desmarca, el cronograma guarda los ciclos tal como los predice el modelo.</span>
            </span>
          </label>
          <label className="flex items-start gap-2 text-sm text-texto">
            <Checkbox className="mt-0.5" checked={f.ajustar_pulso_al_total} disabled={deshabilitado} onChange={(e) => setF((x) => ({ ...x, ajustar_pulso_al_total: e.target.checked }))} />
            <span>
              Ajustar el pulso para que el día sume lo que dijo el modelo
              <span className="block text-xs text-texto-2">Sin marcar, cada pulso es el pulso base y el total puede variar por el redondeo.</span>
            </span>
          </label>
        </div>
      </Card>

      <Card>
        <CardHeader titulo="Lo que se calcula" descripcion="Con los valores guardados y los turnos activos del módulo" />
        <div className="p-4"><Derivados d={parametros.derivados} avisos={parametros.avisos} /></div>
      </Card>

      <Card>
        <CardHeader titulo="Suelo y agua disponible" />
        <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Textura del suelo">
            <Input value={f.textura_suelo} maxLength={30} disabled={deshabilitado} onChange={(e) => setF((x) => ({ ...x, textura_suelo: e.target.value }))} />
          </Field>
          {CAMPOS_SUELO.map((c) => <CampoNum key={c.clave} campo={c} f={f} setF={setF} deshabilitado={deshabilitado} />)}
        </div>
      </Card>

      <Card>
        <CardHeader titulo="Sistema de riego" />
        <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
          {CAMPOS_SISTEMA.map((c) => <CampoNum key={c.clave} campo={c} f={f} setF={setF} deshabilitado={deshabilitado} />)}
        </div>
      </Card>

      <Card>
        <CardHeader titulo="Fenología y ventana de riego" />
        <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3">
          <Field label="Fase fenológica actual">
            <Select value={f.fase_fenologica} disabled={deshabilitado} opciones={f.fases.map(({ fase }) => ({ value: fase, label: fase }))} onValueChange={(v) => setF((x) => ({ ...x, fase_fenologica: v }))} />
          </Field>
          <Field label="Modo de ventana">
            <Select value={f.modo_ventana} disabled={deshabilitado} opciones={MODOS} onValueChange={(v) => setF((x) => ({ ...x, modo_ventana: v as Formulario["modo_ventana"] }))} />
          </Field>
          {CAMPOS_VENTANA.map((c) => <CampoNum key={c.clave} campo={c} f={f} setF={setF} deshabilitado={deshabilitado} />)}
          <label className="flex items-start gap-2 text-sm text-texto sm:col-span-2">
            <Checkbox className="mt-0.5" checked={f.agotamiento_automatico} disabled={deshabilitado} onChange={(e) => setF((x) => ({ ...x, agotamiento_automatico: e.target.checked }))} />
            <span>
              Agotamiento operativo automático
              <span className="block text-xs text-texto-2">Usa el menor entre el de la fase y el máximo que cabe en un bloque de 3 h con todos los turnos.</span>
            </span>
          </label>
        </div>
        <div className="px-4 pb-4">
          <h3 className="mb-2 text-sm font-semibold text-texto">Agotamiento por pulso según la fase (% del agua disponible)</h3>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {f.fases.map((fila, i) => (
              <Field key={fila.fase} label={fila.fase}>
                <Input inputMode="decimal" value={fila.pct} disabled={deshabilitado} onChange={(e) => {
                  const valor = e.target.value;
                  setF((x) => ({ ...x, fases: x.fases.map((y, j) => (j === i ? { ...y, pct: valor } : y)) }));
                }} />
              </Field>
            ))}
          </div>
        </div>
      </Card>

      <Card>
        <CardHeader titulo="Curvas de aplicación por hora" descripcion="% de la ETr de cada hora; cada curva debe sumar 100 %. Vacío = fuera de su ventana." />
        <div className="max-w-full overflow-x-auto p-4">
          <table className="w-full min-w-[320px] border-collapse text-sm">
            <caption className="sr-only">Curvas de aplicación por hora</caption>
            <thead>
              <tr className="text-left text-xs text-texto-2">
                <th scope="col" className="p-1.5">Hora</th>
                {CURVAS.map((c) => <th key={c} scope="col" className="p-1.5">Curva {c}</th>)}
              </tr>
            </thead>
            <tbody>
              {HORAS.map((h) => (
                <tr key={h} className="border-t border-borde">
                  <th scope="row" className="p-1.5 text-left font-medium tabular-nums text-texto-2">{String(h).padStart(2, "0")}:00</th>
                  {CURVAS.map((c) => (
                    <td key={c} className="p-1">
                      <Input inputMode="decimal" aria-label={`Curva ${c}, ${String(h).padStart(2, "0")}:00`} className="h-8 min-w-16" value={f.curvas[c][h] ?? ""} disabled={deshabilitado}
                        onChange={(e) => {
                          const valor = e.target.value;
                          setF((x) => ({ ...x, curvas: { ...x.curvas, [c]: { ...x.curvas[c], [h]: valor } } }));
                        }} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t-2 border-borde font-semibold">
                <th scope="row" className="p-1.5 text-left">Total</th>
                {CURVAS.map((c) => {
                  const suma = sumaCurva(f, c);
                  return <td key={c} className={cn("p-1.5 tabular-nums", Math.abs(suma - 100) > 0.01 ? "text-err-tx" : "text-ok-tx")}>{num(suma, 0)} %</td>;
                })}
              </tr>
            </tfoot>
          </table>
        </div>
      </Card>

      {errores.length > 0 && <Alert tono="error" titulo="Revisa los datos">{errores.join(". ")}.</Alert>}
      {guardar.isError && <Alert tono="error" titulo="No se pudo guardar">{mensajeDeError(guardar.error)}</Alert>}
      {editable ? (
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={guardar.isPending}>{guardar.isPending ? "Guardando…" : "Guardar parámetros"}</Button>
          <Button type="button" variante="secundario" disabled={guardar.isPending} onClick={() => { setF(aFormulario(parametros)); setErrores([]); }}>Descartar cambios</Button>
        </div>
      ) : (
        <Alert tono="info">Solo administradores y encargados pueden cambiar estos parámetros.</Alert>
      )}
    </form>
  );
}
