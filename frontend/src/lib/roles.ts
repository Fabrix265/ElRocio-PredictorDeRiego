export const ROLES = ["admin", "encargado", "programador", "subgerente"] as const;
export type Rol = (typeof ROLES)[number];

export const ETIQUETA_ROL: Record<Rol, string> = {
  admin: "Administrador",
  encargado: "Encargado",
  programador: "Programador",
  subgerente: "Subgerente",
};

/** Acceso por pantalla (propuesta §4). */
export const ACCESO = {
  dashboard: ["admin", "encargado", "subgerente", "programador"],
  generar: ["admin", "encargado"],
  cronogramas: ["admin", "encargado", "subgerente", "programador"],
  riego: ["admin", "encargado", "subgerente", "programador"],
  cargaRiego: ["admin", "encargado"],
  datos: ["admin", "encargado", "subgerente", "programador"],
  auditoria: ["admin", "subgerente"],
  usuarios: ["admin"],
  /** Parámetros del riego por pulsos (los datos fijos de la planilla). */
  parametros: ["admin", "encargado", "subgerente"],
} as const satisfies Record<string, readonly Rol[]>;

export type Pantalla = keyof typeof ACCESO;

export function puedeVer(rol: Rol | undefined | null, pantalla: Pantalla): boolean {
  return !!rol && (ACCESO[pantalla] as readonly Rol[]).includes(rol);
}

/** Acciones dentro de una pantalla (propuesta §4). El backend vuelve a validar cada una. */
export const PERMISOS = {
  corregirCronogramas: ["admin", "encargado"],
  publicarCronogramas: ["admin", "encargado"],
  eliminarCronogramas: ["admin", "encargado"],
  confirmarVisto: ["admin", "programador"],
  solicitarCorreccion: ["admin", "subgerente"],
  mantenerCronograma: ["admin", "encargado"],
  verRevisionCronograma: ["admin", "encargado", "subgerente"],
  registrarVista: ["programador", "subgerente"],
  editarRiego: ["admin", "encargado", "subgerente"],
  /** CSV de refinamiento del modelo (§2.4). */
  exportarRefinamiento: ["admin"],
  /** Generar y regenerar cronogramas con el modelo. */
  generarCronogramas: ["admin", "encargado"],
  /** Subir, confirmar o descartar el Excel de riego. */
  subirExcelRiego: ["admin", "encargado"],
  /** Historial de versiones de un turno-día. */
  verVersionesRiego: ["admin", "encargado", "subgerente"],
  /** «Actualizar ahora» (POST /ingestas/ejecutar). */
  ejecutarIngesta: ["admin", "encargado"],
  /** Lista de corridas de ingesta (GET /ingestas). */
  verIngestas: ["admin", "encargado", "subgerente"],
  /** Editar los parámetros del riego por pulsos (PUT /modulos/{id}/parametros-pulsos). */
  editarParametrosRiego: ["admin", "encargado"],
} as const satisfies Record<string, readonly Rol[]>;

export type Permiso = keyof typeof PERMISOS;

export function puede(rol: Rol | undefined | null, permiso: Permiso): boolean {
  return !!rol && (PERMISOS[permiso] as readonly Rol[]).includes(rol);
}
