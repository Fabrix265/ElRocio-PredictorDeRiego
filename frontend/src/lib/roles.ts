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
  datos: ["admin", "encargado", "subgerente", "programador"],
  auditoria: ["admin", "subgerente"],
  usuarios: ["admin"],
} as const satisfies Record<string, readonly Rol[]>;

export type Pantalla = keyof typeof ACCESO;

export function puedeVer(rol: Rol | undefined | null, pantalla: Pantalla): boolean {
  return !!rol && (ACCESO[pantalla] as readonly Rol[]).includes(rol);
}
