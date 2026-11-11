/**
 * Lee el token de restablecimiento del fragmento de la URL (`#token=...`). El token va en el
 * fragmento para que no llegue a servidores ni registros; tras leerlo se borra de la barra.
 */
export function extraerTokenFragmento(hash: string): string | null {
  const limpio = hash.startsWith("#") ? hash.slice(1) : hash;
  if (!limpio) return null;
  const token = new URLSearchParams(limpio).get("token");
  return token && token.trim() ? token.trim() : null;
}

/** Quita el fragmento de la URL actual sin recargar ni agregar una entrada al historial. */
export function limpiarFragmento(): void {
  if (typeof window === "undefined" || !window.location.hash) return;
  const { pathname, search } = window.location;
  window.history.replaceState(window.history.state, "", pathname + search);
}
