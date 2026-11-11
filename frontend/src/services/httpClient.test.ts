import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  __reiniciarParaPruebas,
  api,
  ApiError,
  fijarAccessToken,
  MENSAJE_SIN_CONEXION,
  obtenerAccessToken,
  pistaOrigenDesarrollo,
  refrescarSesion,
  registrarOyentesSesion,
  solicitar,
  TIEMPO_LIMITE_REFRESH_MS,
} from "./httpClient";
import type { RespuestaSesion } from "./tipos";

const USUARIO = {
  id: 1,
  username: "admin",
  nombre: "Ana Admin",
  correo: "admin@example.com",
  rol: "admin" as const,
  activo: true,
  debe_cambiar_password: false,
  ultimo_acceso_at: null,
};

function sesion(token: string): RespuestaSesion {
  return { access_token: token, token_type: "bearer", expires_in: 1800, usuario: USUARIO };
}

function json(status: number, cuerpo?: unknown): Response {
  return new Response(cuerpo === undefined ? null : JSON.stringify(cuerpo), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function cabeceras(init: RequestInit | undefined): Record<string, string> {
  return (init?.headers ?? {}) as Record<string, string>;
}

/** fetch simulado: /auth/refresh responde con `refresh`; el resto exige el token "nuevo". */
function crearFetch(refresh: () => Promise<Response> | Response) {
  return vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const ruta = String(url);
    if (ruta.endsWith("/auth/refresh")) return refresh();
    const auth = cabeceras(init).Authorization;
    if (auth === "Bearer nuevo") return json(200, { ok: true, ruta });
    return json(401, { detail: "Token vencido" });
  });
}

beforeEach(() => {
  __reiniciarParaPruebas();
  vi.stubGlobal("BroadcastChannel", undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("httpClient: refresh de vuelo único", () => {
  it("varias peticiones con 401 simultáneo comparten un solo refresh y se reintentan una vez", async () => {
    let liberar!: () => void;
    const pendiente = new Promise<void>((r) => (liberar = r));
    const fetchMock = crearFetch(async () => {
      await pendiente;
      return json(200, sesion("nuevo"));
    });
    vi.stubGlobal("fetch", fetchMock);
    const alRenovar = vi.fn();
    registrarOyentesSesion({ alRenovar });
    fijarAccessToken("viejo");

    const peticiones = Promise.all([api.get("/usuarios"), api.get("/auditoria"), api.get("/fundos")]);
    // Deja que las tres reciban el 401 antes de responder el refresh.
    await vi.waitFor(() => expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/auth/refresh"))).toBe(true));
    liberar();
    const resultados = await peticiones;

    const llamadasRefresh = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/auth/refresh"));
    expect(llamadasRefresh).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(7); // 3 originales + 1 refresh + 3 reintentos
    expect(resultados.map((r) => (r as { ok: boolean }).ok)).toEqual([true, true, true]);
    expect(obtenerAccessToken()).toBe("nuevo");
    expect(alRenovar).toHaveBeenCalledTimes(1);

    const [, initRefresh] = llamadasRefresh[0];
    expect(initRefresh?.method).toBe("POST");
    expect(initRefresh?.credentials).toBe("include");
    expect(cabeceras(initRefresh)["X-Requested-With"]).toBe("fetch");
    expect(cabeceras(initRefresh).Authorization).toBeUndefined();
  });

  it("si el refresh falla, avisa la pérdida de sesión y no reintenta", async () => {
    const fetchMock = crearFetch(() => json(401, { detail: "Sesión vencida" }));
    vi.stubGlobal("fetch", fetchMock);
    const alPerder = vi.fn();
    registrarOyentesSesion({ alPerder });
    fijarAccessToken("viejo");

    const r = await Promise.allSettled([api.get("/usuarios"), api.get("/auditoria")]);

    expect(r.every((x) => x.status === "rejected")).toBe(true);
    expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/auth/refresh"))).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(alPerder).toHaveBeenCalled();
    expect(obtenerAccessToken()).toBeNull();
    const error = (r[0] as PromiseRejectedResult).reason;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(401);
  });

  it.each([
    ["503 del pooler", () => json(503, { detail: "Servicio no disponible" }), 503],
    ["502 del proxy (HTML)", () => new Response("<html>Bad Gateway</html>", { status: 502 }), 502],
    ["red caída", () => Promise.reject(new TypeError("Failed to fetch")), 0],
  ])("401 seguido de refresh con %s: informa el error SIN cerrar la sesión", async (_caso, refresh, status) => {
    const fetchMock = crearFetch(refresh as () => Promise<Response>);
    vi.stubGlobal("fetch", fetchMock);
    const alPerder = vi.fn();
    registrarOyentesSesion({ alPerder });
    fijarAccessToken("viejo");

    const error = await api.get("/usuarios").catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(status);
    expect(alPerder).not.toHaveBeenCalled();
    expect(obtenerAccessToken()).toBe("viejo");
    expect(fetchMock).toHaveBeenCalledTimes(2); // original + refresh, sin reintento

    // Cuando el backend vuelve, el siguiente 401 recupera la sesión con la misma cookie.
    fetchMock.mockImplementation(
      crearFetch(() => json(200, sesion("nuevo"))).getMockImplementation()!,
    );
    await expect(api.get("/usuarios")).resolves.toMatchObject({ ok: true });
    expect(obtenerAccessToken()).toBe("nuevo");
    expect(alPerder).not.toHaveBeenCalled();
  });

  it("el refresh tiene tiempo límite: un refresh colgado libera el candado como 'sin conexión'", async () => {
    vi.useFakeTimers();
    try {
      let llamadas = 0;
      const fetchMock = vi.fn(
        (_u: string | URL | Request, init?: RequestInit) =>
          new Promise<Response>((resolver, rechazar) => {
            llamadas += 1;
            if (llamadas > 1) return resolver(json(200, sesion("nuevo")));
            // Nunca responde; solo se corta cuando se aborta la señal.
            init?.signal?.addEventListener("abort", () => rechazar(init.signal?.reason));
          }),
      );
      vi.stubGlobal("fetch", fetchMock);
      const alPerder = vi.fn();
      registrarOyentesSesion({ alPerder });

      const primero = refrescarSesion().catch((e: unknown) => e);
      await vi.advanceTimersByTimeAsync(TIEMPO_LIMITE_REFRESH_MS);
      const error = await primero;
      expect(error).toBeInstanceOf(ApiError);
      expect((error as ApiError).status).toBe(0);
      expect((error as ApiError).detail).toBe(MENSAJE_SIN_CONEXION);
      expect(alPerder).not.toHaveBeenCalled();

      // La promesa compartida se liberó: el siguiente refresh sale y funciona.
      await expect(refrescarSesion()).resolves.toMatchObject({ access_token: "nuevo" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("usa navigator.locks para coordinar el refresh entre pestañas", async () => {
    const request = vi.fn((_nombre: string, fn: () => Promise<unknown>) => fn());
    vi.stubGlobal("navigator", { ...navigator, locks: { request } });
    vi.stubGlobal("fetch", crearFetch(() => json(200, sesion("nuevo"))));

    const [a, b] = await Promise.all([refrescarSesion(), refrescarSesion()]);

    expect(request).toHaveBeenCalledTimes(1);
    expect(request.mock.calls[0][0]).toBe("riego-refresh");
    expect(a?.access_token).toBe("nuevo");
    expect(b).toBe(a);
  });

  it("tras terminar, un nuevo 401 dispara otro refresh (la promesa no queda pegada)", async () => {
    const fetchMock = crearFetch(() => json(200, sesion("nuevo")));
    vi.stubGlobal("fetch", fetchMock);
    await refrescarSesion();
    await refrescarSesion();
    expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/auth/refresh"))).toHaveLength(2);
  });

  it("si otra petición ya renovó el token, reintenta con él sin pedir otro refresh", async () => {
    const fetchMock = vi.fn(async (_u: string | URL | Request, init?: RequestInit) => {
      const auth = cabeceras(init).Authorization;
      if (auth === "Bearer viejo") {
        fijarAccessToken("nuevo"); // simula una renovación concurrente
        return json(401, { detail: "Token vencido" });
      }
      return json(200, { ok: true });
    });
    vi.stubGlobal("fetch", fetchMock);
    fijarAccessToken("viejo");

    await expect(api.get("/fundos")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.some(([u]) => String(u).endsWith("/auth/refresh"))).toBe(false);
  });

  it("las rutas públicas de auth no intentan refresh ante 401", async () => {
    const fetchMock = vi.fn(async () => json(401, { detail: "Usuario o contraseña incorrectos" }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      solicitar("/auth/login", { method: "POST", body: { username: "x", password: "y" }, autenticado: false }),
    ).rejects.toMatchObject({ status: 401, detail: "Usuario o contraseña incorrectos" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.credentials).toBe("include");
  });
});

describe("httpClient: peticiones y errores", () => {
  it("arma la URL con /api/v1, omite filtros vacíos y envía las cabeceras", async () => {
    const fetchMock = vi.fn(async () => json(200, []));
    vi.stubGlobal("fetch", fetchMock);
    fijarAccessToken("tok");
    await api.get("/usuarios", { q: "ana", rol: undefined, activo: false, vacio: "" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/usuarios?q=ana&activo=false");
    expect(cabeceras(init).Authorization).toBe("Bearer tok");
    expect(cabeceras(init)["X-Requested-With"]).toBe("fetch");
    expect(init.credentials).toBe("same-origin");
  });

  it("envía FormData tal cual, sin Content-Type JSON (el navegador pone el boundary)", async () => {
    const fetchMock = vi.fn(async () => json(201, { id: 7 }));
    vi.stubGlobal("fetch", fetchMock);
    fijarAccessToken("tok");
    const formulario = new FormData();
    formulario.append("modulo_id", "3");
    await expect(api.postFormulario("/riego/cargas", formulario)).resolves.toEqual({ id: 7 });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(init.body).toBe(formulario);
    expect(cabeceras(init)["Content-Type"]).toBeUndefined();
    expect(cabeceras(init).Authorization).toBe("Bearer tok");
  });

  it("devuelve undefined en 204", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
    await expect(api.post("/auth/restablecer", { token: "t", password: "p" })).resolves.toBeUndefined();
  });

  it("traduce errores de validación (lista) a un mensaje y conserva los errores", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(422, { detail: [{ loc: ["body", "correo"], msg: "correo inválido", type: "value_error" }] }),
      ),
    );
    const error = await api.post("/usuarios", {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).detail).toBe("Correo: correo inválido");
    expect((error as ApiError).errores).toHaveLength(1);
  });

  it("usa el detail en español del backend y un mensaje genérico si no viene", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(429, { detail: "Demasiados intentos. Vuelve a intentarlo en 15 minutos." })));
    await expect(api.get("/x")).rejects.toMatchObject({ detail: "Demasiados intentos. Vuelve a intentarlo en 15 minutos." });

    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>", { status: 502 })));
    await expect(api.get("/x")).rejects.toMatchObject({ status: 502, detail: expect.stringContaining("servidor") });
  });

  it("muestra los campos de un 422 con su nombre en español (o solo el mensaje)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json(422, {
          detail: [
            { loc: ["query", "q"], msg: "Debe tener como máximo 100 caracteres.", type: "string_too_long" },
            { loc: ["body", "campo_raro"], msg: "Valor no válido.", type: "value_error" },
          ],
        }),
      ),
    );
    const error = await api.get("/usuarios", { q: "x".repeat(120) }).catch((e: unknown) => e);
    expect((error as ApiError).detail).toBe("Búsqueda: Debe tener como máximo 100 caracteres. · Valor no válido.");
    expect((error as ApiError).detail).not.toContain("q:");
  });

  it("en desarrollo, un 403 por Origin en /auth explica cómo configurarlo", () => {
    const pista = pistaOrigenDesarrollo(403, "Solicitud no permitida", true);
    expect(pista).toContain("CORS_ORIGINS");
    expect(pista).toContain(window.location.origin);
    expect(pistaOrigenDesarrollo(403, "Solicitud no permitida", false)).toBe("Solicitud no permitida");
    expect(pistaOrigenDesarrollo(403, "Debes cambiar tu contraseña", true)).toBe("Debes cambiar tu contraseña");
  });

  it("informa sin conexión con status 0", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    await expect(api.get("/x")).rejects.toMatchObject({ status: 0, detail: expect.stringContaining("No se pudo conectar") });
  });
});
