import type { TonoBadge } from "../../components/ui/Badge";
import type {
  CicloRiego,
  EstadoCarga,
  GrupoCarga,
  OrigenRiego,
  RegistroRiego,
  ResultadoCarga,
} from "../../services/riego";

/** Estado visible de una celda turno-día. */
export type EstadoCelda = "aplicado" | "provisional" | "sin_riego" | "sin_registro";

export const ETIQUETA_ESTADO_CELDA: Record<EstadoCelda, string> = {
  aplicado: "Aplicado",
  provisional: "Provisional",
  sin_riego: "Sin riego",
  sin_registro: "Sin registro",
};

export const TONO_ESTADO_CELDA: Record<EstadoCelda, TonoBadge> = {
  aplicado: "exito",
  provisional: "aviso",
  sin_riego: "info",
  sin_registro: "neutro",
};

export const DESCRIPCION_ESTADO_CELDA: Record<EstadoCelda, string> = {
  aplicado: "Riego confirmado",
  provisional: "Pendiente de confirmar",
  sin_riego: "Se declaró que no se regó",
  sin_registro: "Falta registrar el dato",
};

export const ETIQUETA_ORIGEN: Record<OrigenRiego, string> = {
  historico: "Histórico",
  cronograma: "Cronograma",
  excel: "Excel",
  manual: "Manual",
  controlador: "Controlador",
};

export function etiquetaOrigen(origen: string | null | undefined): string {
  if (!origen) return "—";
  return ETIQUETA_ORIGEN[origen as OrigenRiego] ?? origen;
}

/** Un registro `sin_riego` es aplicado o provisional, pero se muestra como «Sin riego». */
export function estadoCelda(registro: Pick<RegistroRiego, "estado" | "sin_riego"> | undefined): EstadoCelda {
  if (!registro) return "sin_registro";
  if (registro.sin_riego) return "sin_riego";
  return registro.estado;
}

export const ETIQUETA_RESULTADO: Record<ResultadoCarga, string> = {
  nuevo: "Nuevo",
  igual: "Igual",
  reemplaza_provisional: "Reemplaza provisional",
  reemplaza_aplicado: "Reemplaza aplicado",
  sin_riego: "Sin riego",
  error: "Error",
};

export const DESCRIPCION_RESULTADO: Record<ResultadoCarga, string> = {
  nuevo: "Turno-día sin registro: se crea aplicado.",
  igual: "Igual al registro vigente: no crea versión.",
  reemplaza_provisional: "Reemplaza el riego provisional por el aplicado del Excel.",
  reemplaza_aplicado: "Reemplaza un riego ya aplicado (los manuales vienen desmarcados).",
  sin_riego: "El archivo trae la fecha pero no filas del turno: se registra «no se regó».",
  error: "No se puede cargar (fecha de hoy o futura, turno o válvula desconocidos, inicio repetido).",
};

export const TONO_RESULTADO: Record<ResultadoCarga, TonoBadge> = {
  nuevo: "exito",
  igual: "neutro",
  reemplaza_provisional: "info",
  reemplaza_aplicado: "aviso",
  sin_riego: "marca",
  error: "error",
};

/** Orden de los contadores en la vista previa. */
export const RESULTADOS: ResultadoCarga[] = [
  "nuevo",
  "igual",
  "reemplaza_provisional",
  "reemplaza_aplicado",
  "sin_riego",
  "error",
];

/** Resultados que se pueden marcar o desmarcar (igual no crea nada; error no se puede aplicar). */
export const RESULTADOS_APLICABLES: ReadonlySet<ResultadoCarga> = new Set([
  "nuevo",
  "reemplaza_provisional",
  "reemplaza_aplicado",
  "sin_riego",
]);

export function esAplicable(grupo: Pick<GrupoCarga, "resultado">): boolean {
  return RESULTADOS_APLICABLES.has(grupo.resultado);
}

export const ETIQUETA_ESTADO_CARGA: Record<EstadoCarga, string> = {
  previsualizada: "Vista previa",
  confirmada: "Confirmada",
  descartada: "Descartada",
  vencida: "Vencida",
};

export const TONO_ESTADO_CARGA: Record<EstadoCarga, TonoBadge> = {
  previsualizada: "info",
  confirmada: "exito",
  descartada: "neutro",
  vencida: "aviso",
};

// ---------------------------------------------------------------------------
// Cálculos
// ---------------------------------------------------------------------------

export interface ResumenCiclos {
  n: number;
  m3ha: number;
  m3: number;
  duracionMin: number;
  /** Primer inicio y último fin ("HH:MM"), con aviso si termina al día siguiente. */
  desde: string | null;
  hasta: string | null;
  finDiaSiguiente: boolean;
}

export function resumirCiclos(ciclos: CicloRiego[] | null | undefined): ResumenCiclos {
  const lista = ciclos ?? [];
  const ordenados = [...lista].sort((a, b) => a.inicio_min - b.inicio_min);
  const ultimo = ordenados.reduce<CicloRiego | null>((max, c) => (!max || c.fin_min > max.fin_min ? c : max), null);
  return {
    n: lista.length,
    m3ha: lista.reduce((s, c) => s + (c.riego_m3ha ?? 0), 0),
    m3: lista.reduce((s, c) => s + (c.riego_m3 ?? 0), 0),
    duracionMin: lista.reduce((s, c) => s + (c.duracion_min ?? 0), 0),
    desde: ordenados[0]?.hora_inicio ?? null,
    hasta: ultimo?.hora_fin ?? null,
    finDiaSiguiente: lista.some((c) => c.fin_dia_siguiente),
  };
}

export type Contadores = Record<ResultadoCarga, { total: number; aplicar: number }>;

export function contarResultados(grupos: GrupoCarga[]): Contadores {
  const base = Object.fromEntries(RESULTADOS.map((r) => [r, { total: 0, aplicar: 0 }])) as Contadores;
  for (const g of grupos) {
    const c = base[g.resultado];
    if (!c) continue;
    c.total += 1;
    if (g.aplicar && esAplicable(g)) c.aplicar += 1;
  }
  return base;
}

/** Turno-días que se crearían al confirmar. */
export function totalAAplicar(grupos: GrupoCarga[]): number {
  return grupos.filter((g) => g.aplicar && esAplicable(g)).length;
}

/** Estado de la casilla de un resultado: todos, ninguno o algunos marcados. */
export function estadoGrupo(grupos: GrupoCarga[], resultado: ResultadoCarga): boolean | "mixto" {
  const delResultado = grupos.filter((g) => g.resultado === resultado);
  const marcados = delResultado.filter((g) => g.aplicar).length;
  if (marcados === 0) return false;
  if (marcados === delResultado.length) return true;
  return "mixto";
}

/** Cambios necesarios para marcar o desmarcar todos los grupos de un resultado. */
export function cambiosParaResultado(grupos: GrupoCarga[], resultado: ResultadoCarga, aplicar: boolean) {
  return grupos
    .filter((g) => g.resultado === resultado && g.aplicar !== aplicar)
    .map((g) => ({ id: g.id, aplicar }));
}

/** Vencimiento de una carga: `vence_at` o 24 h después de subirla. */
export function venceCarga(carga: { vence_at?: string | null; subido_at: string }): Date | null {
  if (carga.vence_at) {
    const d = new Date(carga.vence_at);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  const subida = new Date(carga.subido_at);
  return Number.isNaN(subida.getTime()) ? null : new Date(subida.getTime() + 24 * 3600 * 1000);
}

const fmt1 = new Intl.NumberFormat("es-PE", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const fmt0 = new Intl.NumberFormat("es-PE", { maximumFractionDigits: 0 });

export function formatearM3ha(valor: number | null | undefined): string {
  return valor == null ? "—" : fmt1.format(valor);
}

export function formatearM3(valor: number | null | undefined): string {
  return valor == null ? "—" : fmt0.format(valor);
}

/** "1 h 25 min", "45 min". */
export function formatearDuracion(minutos: number | null | undefined): string {
  if (minutos == null || !Number.isFinite(minutos)) return "—";
  const total = Math.round(minutos);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

export function formatearBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmt1.format(bytes / 1024)} KB`;
  return `${fmt1.format(bytes / (1024 * 1024))} MB`;
}

/** Límites del archivo (propuesta §3.5). El backend vuelve a validar todo. */
export const TAMANO_MAXIMO_EXCEL = 15 * 1024 * 1024;

export function validarArchivoExcel(archivo: File): string | null {
  if (!/\.xlsx$/i.test(archivo.name)) return "El archivo debe ser un Excel .xlsx.";
  if (archivo.size === 0) return "El archivo está vacío.";
  if (archivo.size > TAMANO_MAXIMO_EXCEL) return "El archivo supera el máximo de 15 MB.";
  return null;
}
