import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Sin `globals: true`, Testing Library no limpia el DOM sola entre pruebas.
afterEach(() => {
  cleanup();
});
