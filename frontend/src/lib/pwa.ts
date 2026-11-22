import { useSyncExternalStore } from "react";

/**
 * PWA: registro del service worker, instalación y aviso de versión nueva.
 *
 * Un único estado compartido (fuera de React) que los componentes leen con `usePwa()`.
 * - Instalar: el navegador dispara `beforeinstallprompt`; lo guardamos para ofrecer un botón propio.
 * - Actualizar: cuando hay un service worker nuevo en espera, se avisa y el usuario decide cuándo
 *   recargar (nunca a mitad de una edición).
 * - Conexión: `enLinea` alimenta el aviso «Sin conexión».
 */

interface EventoInstalacion extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

interface EstadoPwa {
  promptInstalacion: EventoInstalacion | null;
  instalada: boolean;
  enLinea: boolean;
  esperando: ServiceWorker | null;
}

const enNavegador = typeof window !== "undefined";

let estado: EstadoPwa = {
  promptInstalacion: null,
  instalada: enNavegador && typeof window.matchMedia === "function" && window.matchMedia("(display-mode: standalone)").matches,
  enLinea: enNavegador ? navigator.onLine !== false : true,
  esperando: null,
};
const oyentes = new Set<() => void>();
let iniciada = false;
let actualizacionPedida = false;

function fijar(parcial: Partial<EstadoPwa>) {
  estado = { ...estado, ...parcial };
  oyentes.forEach((oyente) => oyente());
}

function suscribir(oyente: () => void) {
  oyentes.add(oyente);
  return () => oyentes.delete(oyente);
}

function vigilarRegistro(registro: ServiceWorkerRegistration) {
  if (registro.waiting && navigator.serviceWorker.controller) fijar({ esperando: registro.waiting });
  registro.addEventListener("updatefound", () => {
    const nuevo = registro.installing;
    nuevo?.addEventListener("statechange", () => {
      // Solo es «versión nueva» si ya había uno controlando la página (no en la primera visita).
      if (nuevo.state === "installed" && navigator.serviceWorker.controller) fijar({ esperando: nuevo });
    });
  });
}

/** Se llama una vez al arrancar la app (main.tsx). */
export function iniciarPwa() {
  if (!enNavegador || iniciada) return;
  iniciada = true;

  window.addEventListener("beforeinstallprompt", (evento) => {
    evento.preventDefault();
    fijar({ promptInstalacion: evento as EventoInstalacion });
  });
  window.addEventListener("appinstalled", () => fijar({ promptInstalacion: null, instalada: true }));
  window.addEventListener("online", () => fijar({ enLinea: true }));
  window.addEventListener("offline", () => fijar({ enLinea: false }));

  // En desarrollo el service worker interferiría con Vite: solo en producción.
  if (import.meta.env.PROD && "serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (actualizacionPedida) window.location.reload();
    });
    window.addEventListener("load", () => {
      navigator.serviceWorker
        .register("/sw.js")
        .then((registro) => {
          vigilarRegistro(registro);
          // Revisa si hay versión nueva cada hora (la app suele quedar abierta todo el día).
          window.setInterval(() => void registro.update().catch(() => undefined), 60 * 60 * 1000);
        })
        .catch(() => {
          /* sin service worker la app funciona igual; solo no es instalable */
        });
    });
  }
}

/** Abre el diálogo de instalación del navegador. */
export async function instalarApp() {
  const prompt = estado.promptInstalacion;
  if (!prompt) return;
  await prompt.prompt();
  const { outcome } = await prompt.userChoice;
  fijar({ promptInstalacion: null, instalada: outcome === "accepted" || estado.instalada });
}

/** Activa la versión nueva en espera y recarga la página. */
export function actualizarApp() {
  if (!estado.esperando) return;
  actualizacionPedida = true;
  estado.esperando.postMessage({ tipo: "SALTAR_ESPERA" });
}

export function descartarActualizacion() {
  fijar({ esperando: null });
}

export function usePwa() {
  const actual = useSyncExternalStore(suscribir, () => estado, () => estado);
  return {
    instalable: !!actual.promptInstalacion && !actual.instalada,
    instalada: actual.instalada,
    enLinea: actual.enLinea,
    hayActualizacion: !!actual.esperando,
  };
}
