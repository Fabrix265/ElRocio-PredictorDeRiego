import "@fontsource/ibm-plex-sans/latin-400.css";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-sans/latin-700.css";
import "./index.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { iniciarPwa } from "./lib/pwa";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// PWA: service worker (solo en producción), instalación y aviso de versión nueva (ver lib/pwa.ts).
iniciarPwa();
