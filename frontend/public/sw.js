/* Service worker del Plan de Riego (F6: solo estructura).
 *
 * Hace la app instalable y deja preparado el ciclo de vida. A propósito NO guarda en caché la API
 * ni los datos: los cronogramas y el riego cambian durante el día y nunca deben verse viejos.
 * Solo guarda la página de inicio para mostrar un aviso sin conexión cuando falla la red al
 * navegar. Para activar caché sin conexión más adelante, versionar CACHE y ampliar PRECARGA.
 */
const CACHE = "riego-v1";
const PRECARGA = ["/", "/favicon.svg", "/icono-192.png"];

self.addEventListener("install", (evento) => {
  evento.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECARGA)));
  self.skipWaiting();
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches.keys().then((claves) => Promise.all(claves.filter((c) => c !== CACHE).map((c) => caches.delete(c)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (evento) => {
  const { request } = evento;
  const url = new URL(request.url);
  // La API y lo que no es GET van siempre a la red, sin tocar.
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  // Navegación: red primero; sin red, la página de inicio guardada (la app muestra su propio aviso).
  if (request.mode === "navigate") {
    evento.respondWith(fetch(request).catch(() => caches.match("/")));
  }
});
