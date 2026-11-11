/**
 * Sanea el parámetro `next` del login: solo se aceptan rutas relativas de la propia app
 * (empiezan con "/" y no con "//" ni "/\"), sin caracteres de control ni barras invertidas.
 * Cualquier otro valor (URL absoluta, "javascript:", vacío) vuelve al inicio.
 */
export function sanearNext(valor: string | null | undefined, porDefecto = "/"): string {
  if (!valor) return porDefecto;
  const ruta = valor.trim();
  if (!ruta.startsWith("/")) return porDefecto;
  if (ruta.startsWith("//")) return porDefecto;
  if (ruta.includes("\\")) return porDefecto;
  if (/[\u0000-\u001f\u007f]/.test(ruta)) return porDefecto;
  // Evita bucles volviendo a las pantallas públicas de acceso.
  const camino = ruta.split(/[?#]/)[0];
  if (["/login", "/recuperar", "/restablecer"].includes(camino)) return porDefecto;
  return ruta;
}

/** Construye la URL del login guardando la ruta actual en `next`. */
export function urlLoginCon(rutaActual: string): string {
  const next = sanearNext(rutaActual, "");
  return next && next !== "/" ? `/login?next=${encodeURIComponent(next)}` : "/login";
}
