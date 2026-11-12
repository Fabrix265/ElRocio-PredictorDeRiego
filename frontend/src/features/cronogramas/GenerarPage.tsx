import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Sparkles } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { Alert } from "../../components/ui/Alert";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { Checkbox } from "../../components/ui/Checkbox";
import { EmptyState } from "../../components/ui/EmptyState";
import { Field } from "../../components/ui/Field";
import { Input } from "../../components/ui/Input";
import { PageHeader } from "../../components/ui/PageHeader";
import { esDiaValido, formatearDiaCorto, hoyLima, sumarDias } from "../../lib/fechas";
import { mensajeDeError } from "../../services/httpClient";
import { claveCronogramas, cronogramasApi, type GenerarSalida } from "../../services/cronogramas";
import { useSeleccion } from "../catalogo/SeleccionProvider";
import { ContextoDiaAnterior, RangoContextoDiaAnterior } from "./ContextoDiaAnterior";
import { ETIQUETA_ACCION, MarcasVersion, TONO_ACCION } from "./etiquetas";

export const DIAS_MAX = 7;

/** Valida el formulario (mismas reglas que el backend); null si es válido. */
export function validarGenerar(fecha: string, dias: number, hoy: string): string | null {
  if (!esDiaValido(fecha)) return "Elige la fecha inicial.";
  if (fecha < sumarDias(hoy, -7) || fecha > sumarDias(hoy, 1))
    return `La fecha inicial debe estar entre el ${formatearDiaCorto(sumarDias(hoy, -7))} y mañana.`;
  if (!Number.isInteger(dias) || dias < 1 || dias > DIAS_MAX) return `El número de días va de 1 a ${DIAS_MAX}.`;
  return null;
}

export default function GenerarPage() {
  const { modulo } = useSeleccion();
  const hoy = hoyLima();
  const queryClient = useQueryClient();
  const [fecha, setFecha] = useState(hoy);
  const [dias, setDias] = useState(3);
  const [regenerar, setRegenerar] = useState(false);
  const [resultado, setResultado] = useState<GenerarSalida | null>(null);

  const error = validarGenerar(fecha, dias, hoy);
  const generar = useMutation({
    mutationFn: () =>
      cronogramasApi.generar({ modulo_id: modulo!.id, fecha_inicio: fecha, dias, regenerar_existentes: regenerar }),
    onSuccess: (r) => {
      setResultado(r);
      void queryClient.invalidateQueries({ queryKey: claveCronogramas.todo });
    },
  });

  const enviar = (e: FormEvent) => {
    e.preventDefault();
    if (!error && modulo) generar.mutate();
  };

  const atrasadas = resultado?.frescura.fuentes.filter((f) => !f.informativa && f.estado !== "verde") ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        antetitulo="Operación"
        titulo="Generar"
        descripcion={
          modulo
            ? `Calcula con el modelo los cronogramas de ${modulo.codigo}. Los días que ya tienen correcciones o están publicados no se tocan, salvo que lo marques.`
            : "Calcula con el modelo los cronogramas de uno o más días."
        }
      />

      {!modulo ? (
        <Card>
          <EmptyState compacto icono={<Sparkles />} titulo="Elige un módulo" descripcion="Usa el selector Fundo › Módulo de la cabecera." />
        </Card>
      ) : (
        <Card>
          <form onSubmit={enviar} className="flex flex-col gap-4 p-4" noValidate>
            <div className="grid grid-cols-2 gap-3 sm:flex sm:flex-wrap sm:items-end">
              <Field label="Fecha inicial" className="sm:w-44" ayuda="Primer día: desde 7 días atrás hasta mañana.">
                <Input
                  type="date"
                  value={fecha}
                  min={sumarDias(hoy, -7)}
                  max={sumarDias(hoy, 1)}
                  onChange={(e) => setFecha(e.target.value)}
                />
              </Field>
              <Field label="Días" className="sm:w-44" ayuda="De 1 a 7 días seguidos.">
                <Input
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={DIAS_MAX}
                  value={Number.isNaN(dias) ? "" : dias}
                  onChange={(e) => setDias(e.target.valueAsNumber)}
                />
              </Field>
            </div>
            <ul className="list-disc space-y-1 pl-4 text-xs text-texto-2">
              <li>Un solo cronograma por día: un borrador sin correcciones recibe una versión nueva.</li>
              <li>Los días con correcciones o publicados se omiten, salvo que marques la casilla.</li>
              <li>Desde el segundo día, el plan es preliminar: usa el riego que el modelo predijo para el día anterior.</li>
            </ul>
            <label className="flex items-start gap-2 text-sm text-texto">
              <Checkbox
                className="mt-0.5"
                aria-label="Regenerar también los días con correcciones o publicados"
                checked={regenerar}
                onChange={(e) => setRegenerar(e.target.checked)}
              />
              <span>
                Regenerar también los días con correcciones o publicados
                <span className="block text-xs text-texto-2">
                  Se crea una versión nueva del modelo como borrador (de cambios); lo publicado no cambia hasta que se publique.
                </span>
              </span>
            </label>
            {error && <Alert tono="aviso">{error}</Alert>}
            {generar.isError && (
              <Alert tono="error" titulo="No se pudo generar">
                {mensajeDeError(generar.error)}
              </Alert>
            )}
            <div>
              <Button type="submit" disabled={!!error || generar.isPending}>
                <Sparkles aria-hidden="true" />
                {generar.isPending ? "Generando…" : "Generar"}
              </Button>
              {generar.isPending && <span className="ml-3 text-xs text-texto-2">El modelo tarda unos segundos por día.</span>}
            </div>
          </form>
        </Card>
      )}

      {resultado && (
        <Card>
          <CardHeader
            titulo="Resultado por día"
            descripcion={`Modelo ${resultado.modelo_version}${resultado.duracion_ms ? ` · ${(resultado.duracion_ms / 1000).toFixed(1)} s` : ""}`}
          />
          {atrasadas.length > 0 && (
            <div className="px-4 pt-3">
              <Alert tono="aviso" titulo="Datos atrasados al generar">
                {atrasadas.map((f) => f.nombre).join(", ")}: sin el día anterior completo. El plan se calculó igual, con menos precisión.
              </Alert>
            </div>
          )}
          <RangoContextoDiaAnterior fechas={resultado.dias_resultado.map((d) => d.fecha)} moduloId={resultado.modulo_id}>
          <ul className="divide-y divide-borde">
            {resultado.dias_resultado.map((d) => (
              <li key={d.fecha} className="flex min-w-0 flex-col gap-2 px-4 py-3">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="w-24 text-sm font-semibold text-texto">{formatearDiaCorto(d.fecha)}</span>
                  <Badge tono={TONO_ACCION[d.accion]}>{ETIQUETA_ACCION[d.accion]}</Badge>
                  {d.version != null && <span className="text-xs text-texto-2">v{d.version}{d.borrador_de_cambios ? " · borrador de cambios" : ""}</span>}
                  <MarcasVersion marcas={{ preliminar: d.preliminar, datos_incompletos: d.datos_incompletos }} />
                  {d.mensaje && <span className="text-xs text-texto-2">{d.mensaje}</span>}
                </div>
                {d.cronograma_id != null && (
                  <Link
                    to={`/cronogramas/${d.cronograma_id}`}
                    className="inline-flex items-center gap-1 text-sm font-semibold text-marca hover:underline"
                  >
                    Ver detalle <ArrowRight className="size-4" aria-hidden="true" />
                  </Link>
                )}
                </div>
                <ContextoDiaAnterior fecha={d.fecha} />
              </li>
            ))}
          </ul>
          </RangoContextoDiaAnterior>
        </Card>
      )}
    </div>
  );
}
