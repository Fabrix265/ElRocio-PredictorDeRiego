import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileSpreadsheet, Upload, X } from "lucide-react";
import { useId, useRef, useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router";

import { Alert } from "../../components/ui/Alert";
import { Button, clasesBoton } from "../../components/ui/Button";
import { Card, CardBody, CardHeader } from "../../components/ui/Card";
import { PageHeader } from "../../components/ui/PageHeader";
import { cn } from "../../lib/cn";
import { mensajeDeError } from "../../services/httpClient";
import { claveRiego, riegoApi } from "../../services/riego";
import { useSeleccion } from "../catalogo/SeleccionProvider";
import { formatearBytes, validarArchivoExcel } from "./etiquetas";
import { PasosCarga } from "./PasosCarga";

/** Paso 1 del asistente: elegir el Excel de riego y subirlo para ver la vista previa. */
export default function CargaNuevaPage() {
  const { modulo } = useSeleccion();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const idInput = useId();
  const input = useRef<HTMLInputElement>(null);
  const [archivo, setArchivo] = useState<File | null>(null);
  const [errorArchivo, setErrorArchivo] = useState<string | null>(null);
  const [arrastrando, setArrastrando] = useState(false);

  const subir = useMutation({
    mutationFn: ({ moduloId, archivo }: { moduloId: number; archivo: File }) => riegoApi.subirCarga(moduloId, archivo),
    onSuccess: (carga) => {
      queryClient.setQueryData(claveRiego.carga(carga.id), carga);
      navigate(`/riego/cargas/${carga.id}`);
    },
  });

  const elegir = (f: File | null | undefined) => {
    subir.reset();
    if (!f) return;
    const error = validarArchivoExcel(f);
    setErrorArchivo(error);
    setArchivo(error ? null : f);
  };

  const alSoltar = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setArrastrando(false);
    elegir(e.dataTransfer.files?.[0]);
  };

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        antetitulo="Riego aplicado"
        titulo="Cargar Excel de riego"
        descripcion="Sube el Excel del controlador; antes de guardar nada verás qué turno-días son nuevos, iguales o reemplazan un registro."
        acciones={
          <Link to="/riego" className={clasesBoton("fantasma")}>
            <ArrowLeft aria-hidden="true" />
            Volver
          </Link>
        }
      />
      <PasosCarga actual={1} />

      <Card>
        <CardHeader
          titulo="Archivo"
          descripcion={modulo ? `Módulo ${modulo.codigo} · hoja ${modulo.codigo.split("-").pop()} con sus 10 columnas` : undefined}
        />
        <CardBody className="flex flex-col gap-4">
          <label
            htmlFor={idInput}
            onDragOver={(e) => {
              e.preventDefault();
              setArrastrando(true);
            }}
            onDragLeave={() => setArrastrando(false)}
            onDrop={alSoltar}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors",
              arrastrando ? "border-marca bg-activo-bg" : "border-borde bg-fondo hover:border-green-400 hover:bg-activo-bg",
            )}
          >
            <span className="flex size-12 items-center justify-center rounded-full bg-green-50 text-green-600" aria-hidden="true">
              <FileSpreadsheet className="size-6" />
            </span>
            <span className="text-sm font-semibold text-texto">Arrastra el archivo aquí o toca para elegirlo</span>
            <span className="text-xs text-texto-2">Excel .xlsx de hasta 15 MB. Puede ser el archivo acumulado completo.</span>
            <input
              id={idInput}
              ref={input}
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              className="sr-only"
              aria-label="Archivo Excel de riego"
              onChange={(e) => elegir(e.target.files?.[0])}
            />
          </label>

          {errorArchivo && <Alert tono="error">{errorArchivo}</Alert>}

          {archivo && (
            <div className="flex items-center justify-between gap-3 rounded-md border border-borde px-3 py-2.5">
              <div className="flex min-w-0 items-center gap-2">
                <FileSpreadsheet className="size-4 shrink-0 text-green-600" aria-hidden="true" />
                <span className="truncate text-[13px] font-medium">{archivo.name}</span>
                <span className="cifras shrink-0 text-xs text-texto-3">{formatearBytes(archivo.size)}</span>
              </div>
              <Button
                variante="fantasma"
                tamano="icono"
                aria-label="Quitar archivo"
                onClick={() => {
                  setArchivo(null);
                  subir.reset();
                  if (input.current) input.current.value = "";
                }}
                icono={<X aria-hidden="true" />}
              />
            </div>
          )}

          {subir.isError && (
            <Alert tono="error" titulo="No se pudo procesar el archivo">
              {mensajeDeError(subir.error)}
            </Alert>
          )}

          <ul className="list-disc pl-5 text-xs leading-5 text-texto-2">
            <li>Subir otra vez el archivo completo solo marca como «igual» lo que ya está cargado.</li>
            <li>Si una fecha del archivo no trae filas de un turno, se propone «sin riego» (puedes desmarcarlo).</li>
            <li>La vista previa vence a las 24 horas o si alguien cambia uno de los registros comparados.</li>
          </ul>

          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Link to="/riego" className={clasesBoton("secundario")}>
              Cancelar
            </Link>
            <Button
              icono={<Upload aria-hidden="true" />}
              disabled={!archivo || !modulo}
              cargando={subir.isPending}
              onClick={() => archivo && modulo && subir.mutate({ moduloId: modulo.id, archivo })}
            >
              {subir.isPending ? "Procesando…" : "Subir y revisar"}
            </Button>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
