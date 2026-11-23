/* Service worker del Plan de Riego.
 *
 * Qué guarda y qué no:
 * - NUNCA guarda la API ni los datos: los cronogramas y el riego cambian durante el día y no deben
 *   verse viejos. Todo /api/ va siempre a la red.
 * - Guarda la «cáscara» de la app (HTML de inicio, íconos y los archivos de /assets/, que llevan
 *   hash en el nombre y nunca cambian) para que abra rápido y funcione la pantalla sin conexión.
 * - Sin red al navegar: la app guardada (que muestra su aviso «Sin conexión»); si tampoco hay,
 *   la página offline.html.
 *
 * Versión nueva: queda en espera hasta que el usuario pulsa «Actualizar» (mensaje SALTAR_ESPERA),
 * para no recargar a mitad de una edición.
 */
const VERSION = "riego-v2";
const CACHE_CASCARA = `${VERSION}-cascara`;
const CACHE_ASSETS = `${VERSION}-assets`;
const PRECARGA = ["/", "/offline.html", "/favicon.svg", "/icono-192.png", "/icono-512.png", "/manifest.webmanifest"];

self.addEventListener("install", (evento) => {
  evento.waitUntil(caches.open(CACHE_CASCARA).then((cache) => cache.addAll(PRECARGA)));
});

self.addEventListener("activate", (evento) => {
  evento.waitUntil(
    caches
      .keys()
      .then((claves) => Promise.all(claves.filter((c) => !c.startsWith(VERSION)).map((c) => caches.delete(c))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (evento) => {
  if (evento.data && evento.data.tipo === "SALTAR_ESPERA") self.skipWaiting();
});

self.addEventListener("fetch", (evento) => {
  const { request } = evento;
  const url = new URL(request.url);
  // La API, lo que no es GET y otros orígenes van siempre a la red, sin tocar.
  if (request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  // Navegación: red primero (y se refresca la copia de inicio); sin red, la app guardada u offline.html.
  if (request.mode === "navigate") {
    evento.respondWith(
      fetch(request)
        .then((respuesta) => {
          if (respuesta.ok) {
            const copia = respuesta.clone();
            caches.open(CACHE_CASCARA).then((cache) => cache.put("/", copia));
          }
          return respuesta;
        })
        .catch(async () => (await caches.match("/")) || (await caches.match("/offline.html"))),
    );
    return;
  }

  // Archivos con hash (/assets/…): caché primero; si no está, red y se guarda.
  if (url.pathname.startsWith("/assets/")) {
    evento.respondWith(
      caches.match(request).then(
        (guardada) =>
          guardada ||
          fetch(request).then((respuesta) => {
            if (respuesta.ok) {
              const copia = respuesta.clone();
              caches.open(CACHE_ASSETS).then((cache) => cache.put(request, copia));
            }
            return respuesta;
          }),
      ),
    );
    return;
  }

  // Íconos y manifiesto: lo guardado, si existe; si no, la red.
  if (PRECARGA.includes(url.pathname)) {
    evento.respondWith(caches.match(request).then((guardada) => guardada || fetch(request)));
  }
});
