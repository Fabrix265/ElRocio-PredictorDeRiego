/**
 * Preferencias de interfaz por navegador (barra lateral colapsada, último módulo elegido).
 * Nunca datos de sesión. Si el almacenamiento no está disponible, se ignora.
 */
const PREFIJO = "riego.";

export function leerPreferencia(clave: string): string | null {
  try {
    return window.localStorage.getItem(PREFIJO + clave);
  } catch {
    return null;
  }
}

export function guardarPreferencia(clave: string, valor: string | null): void {
  try {
    if (valor === null) window.localStorage.removeItem(PREFIJO + clave);
    else window.localStorage.setItem(PREFIJO + clave, valor);
  } catch {
    // Almacenamiento bloqueado (modo privado): no es crítico.
  }
}
