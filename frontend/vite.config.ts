/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Con VITE_API_URL vacío el frontend llama al mismo origen y Vite reenvía /api al backend.
      "/api": {
        // API_PROXY_TARGET permite apuntar a otro backend local (por defecto, uvicorn en :8000).
        target: process.env.API_PROXY_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    rolldownOptions: {
      output: {
        // Librerías en trozos estables (mejor caché entre despliegues; ninguno supera 500 kB).
        codeSplitting: {
          groups: [
            { name: "react", test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/, priority: 30 },
            { name: "router", test: /node_modules[\\/]react-router[\\/]/, priority: 20 },
            { name: "formularios", test: /node_modules[\\/](zod|react-hook-form|@hookform)[\\/]/, priority: 20 },
            { name: "datos", test: /node_modules[\\/]@tanstack[\\/]/, priority: 20 },
            { name: "ui", test: /node_modules[\\/](@radix-ui|@floating-ui|sonner|lucide-react|react-remove-scroll.*|aria-hidden|tslib|use-sidecar|use-callback-ref|react-style-singleton|get-nonce|detect-node-es)[\\/]/, priority: 10 },
          ],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    restoreMocks: true,
  },
});
