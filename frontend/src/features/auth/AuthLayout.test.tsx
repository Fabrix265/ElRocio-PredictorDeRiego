import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthLayout } from "./AuthLayout";

describe("AuthLayout", () => {
  it("muestra los logos de las tres empresas del grupo", () => {
    render(
      <AuthLayout titulo="Iniciar sesión">
        <p>formulario</p>
      </AuthLayout>,
    );
    const lista = screen.getByRole("list", { name: "Empresas del grupo" });
    const logos = within(lista).getAllByRole("img");
    expect(logos.map((logo) => logo.getAttribute("alt"))).toEqual(["AvoPerú", "Talsa", "Jordie Inversiones"]);
  });
});
