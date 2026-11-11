/**
 * Política de contraseña (la misma que valida el backend, propuesta §7 y
 * backend/app/core/security.py): de 10 a 128 caracteres, con letras y números, y distinta del usuario.
 */
export const PASSWORD_MIN = 10;
export const PASSWORD_MAX = 128;

export function erroresPassword(password: string, username?: string | null): string[] {
  const errores: string[] = [];
  if (password.length < PASSWORD_MIN) errores.push(`Debe tener al menos ${PASSWORD_MIN} caracteres.`);
  if (password.length > PASSWORD_MAX) errores.push(`No puede tener más de ${PASSWORD_MAX} caracteres.`);
  if (!/\p{L}/u.test(password)) errores.push("Debe incluir al menos una letra.");
  if (!/\p{Nd}/u.test(password)) errores.push("Debe incluir al menos un número.");
  const usuario = username?.trim().toLowerCase();
  if (usuario && password.trim().toLowerCase() === usuario) {
    errores.push("No puede ser igual al nombre de usuario.");
  }
  return errores;
}

export function passwordValida(password: string, username?: string | null): boolean {
  return erroresPassword(password, username).length === 0;
}

export const AYUDA_PASSWORD = `Mínimo ${PASSWORD_MIN} caracteres, con letras y números, distinta del usuario.`;

const LETRAS = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"; // sin l, o, I, O (se confunden)
const DIGITOS = "23456789"; // sin 0 ni 1

/** Contraseña temporal aleatoria (criptográfica) que cumple la política: 12 caracteres, letras y números. */
export function generarPasswordTemporal(largo = 12): string {
  const alfabeto = LETRAS + DIGITOS;
  const azar = new Uint32Array(largo);
  crypto.getRandomValues(azar);
  const chars = Array.from(azar, (n) => alfabeto[n % alfabeto.length]);
  // Garantiza al menos una letra y un número en posiciones aleatorias distintas.
  const pos = new Uint32Array(3);
  crypto.getRandomValues(pos);
  const iLetra = pos[0] % largo;
  const iDigito = (iLetra + 1 + (pos[1] % (largo - 1))) % largo;
  chars[iLetra] = LETRAS[pos[2] % LETRAS.length];
  chars[iDigito] = DIGITOS[pos[2] % DIGITOS.length];
  return chars.join("");
}
