import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { __reiniciarParaPruebas } from "../../services/httpClient";
import type { RespuestaSesion } from "../../services/tipos";
import { AuthProvider } from "./AuthProvider";
import { LoginPage } from "./pages/LoginPage";
import { RutaProtegida } from "./RutaProtegida";

const SESION: RespuestaSesion = {
  access_token: "tok",
  token_type: "bearer",
  expires_in: 1800,
  usuario: {
    id: 1,
    username: "ana",
    nombre: "Ana Admin",
    correo: "ana@example.com",
    rol: "admin",
    activo: true,
    debe_cambiar_password: false,
    ultimo_acceso_at: null,
  },
};

function json(status: number, cuerpo?: unknown): Response {
  return new Response(cuerpo === undefined ? null : JSON.stringify(cuerpo), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function Ubicacion() {
  const l = useLocation();
  return <p data-testid="ubicacion">{l.pathname + l.search}</p>;
}

function montar(ruta: string) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[ruta]}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/privado"
              element={
                <RutaProtegida>
                  <p>Contenido privado</p>
                </RutaProtegida>
              }
            />
            <Route path="*" element={<Ubicacion />} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  __reiniciarParaPruebas();
  vi.stubGlobal("BroadcastChannel", undefined);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AuthProvider: refresh silencioso al cargar", () => {
  it("si el refresh inicial da 503, muestra 'No se pudo conectar' (no el login) y Reintentar recupera la sesión", async () => {
    const fetchMock = vi.fn(async () => json(503, { detail: "Servicio no disponible" }));
    vi.stubGlobal("fetch", fetchMock);

    montar("/privado");

    expect(await screen.findByRole("heading", { name: "No se pudo conectar" })).toBeInTheDocument();
    expect(screen.queryByText("Contenido privado")).not.toBeInTheDocument();
    expect(screen.queryByTestId("ubicacion")).not.toBeInTheDocument(); // no redirigió al login

    fetchMock.mockImplementation(async () => json(200, SESION));
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));

    expect(await screen.findByText("Contenido privado")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("sin red, el login también muestra 'No se pudo conectar' en vez del formulario", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Promise.reject(new TypeError("Failed to fetch"))));
    montar("/login");
    expect(await screen.findByRole("heading", { name: "No se pudo conectar" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });

  it("si el backend rechaza el refresh (401), manda al login con next", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(401, { detail: "Sesión vencida" })));
    montar("/privado");
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
    expect(await screen.findByLabelText("Usuario")).toBeEnabled();
  });

  it("mientras verifica la sesión, el login muestra su propio esqueleto (no el layout interno)", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));
    montar("/login");
    expect(screen.getByText("Verificando tu sesión…")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});
