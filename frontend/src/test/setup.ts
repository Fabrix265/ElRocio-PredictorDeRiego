import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom con 13 archivos en paralelo puede tardar más de 1 s en pintar una página entera:
// los findBy*/waitFor esperan hasta 5 s (solo afecta cuánto esperan, no qué comprueban).
configure({ asyncUtilTimeout: 5000 });

// Sin `globals: true`, Testing Library no limpia el DOM sola entre pruebas.
afterEach(() => {
  cleanup();
});
