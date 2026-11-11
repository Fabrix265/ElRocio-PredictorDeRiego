import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Usuario } from "../../services/tipos";
import UsuariosPage from "./UsuariosPage";

function usuario(id: number, nombre: string, extra: Partial<Usuario> = {}): Usuario {
  return {
    id,
    username: nombre.toLowerCase().replace(/\s+/g, "."),
    nombre,
    correo: `u${id}@example.com`,
    rol: "admin",
    activo: true,
    debe_cambiar_password: false,
    ultimo_acceso_at: null,
    ...extra,
  };
}

const YO = usuario(1, "Ana Admin");
const OTRO = usuario(2, "Luis Paredes", { rol: "programador" });

vi.mock("../auth/AuthProvider", () => ({ useUsuario: () => YO }));
vi.mock("./api", async (original) => {
  const real = await original<typeof import("./api")>();
  return { ...real, usuariosApi: { ...real.usuariosApi, listar: vi.fn(async () => [YO, OTRO]) } };
});

beforeEach(() => {
  // Radix usa APIs de puntero que jsdom no trae.
  Element.prototype.hasPointerCapture ??= () => false;
  Element.prototype.releasePointerCapture ??= () => {};
  Element.prototype.scrollIntoView ??= () => {};
});

function montar() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/usuarios"]}>
        <Routes>
          <Route path="/usuarios" element={<UsuariosPage />} />
          <Route path="/cambiar-password" element={<p>Pantalla cambiar contraseña</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function abrirAcciones(nombre: string) {
  await userEvent.click(await screen.findByRole("button", { name: `Acciones para ${nombre}` }));
  return screen.findByRole("menu");
}

describe("UsuariosPage", () => {
  it("para uno mismo no ofrece asignar contraseña temporal (cerraría su sesión): lleva a cambiarla", async () => {
    montar();
    const menu = await abrirAcciones(YO.nombre);
    expect(within(menu).queryByText("Asignar contraseña temporal")).not.toBeInTheDocument();
    await userEvent.click(within(menu).getByText("Cambiar mi contraseña"));
    expect(await screen.findByText("Pantalla cambiar contraseña")).toBeInTheDocument();
  });

  it("para otro usuario sí ofrece asignar contraseña temporal", async () => {
    montar();
    const menu = await abrirAcciones(OTRO.nombre);
    expect(within(menu).getByText("Asignar contraseña temporal")).toBeInTheDocument();
  });

  it("la búsqueda respeta el límite de 100 caracteres del backend", async () => {
    montar();
    expect(await screen.findByLabelText("Buscar")).toHaveAttribute("maxLength", "100");
  });
});
