import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CalendarDays, ChartLine, Sparkles } from "lucide-react";
import { lazy, Suspense } from "react";
import { BrowserRouter, Outlet, Route, Routes } from "react-router";

import { Toaster } from "./components/ui/Toast";
import { TooltipProvider } from "./components/ui/Tooltip";
import { AuthProvider } from "./features/auth/AuthProvider";
import { CambiarPasswordPage } from "./features/auth/pages/CambiarPasswordPage";
import { LoginPage } from "./features/auth/pages/LoginPage";
import { RecuperarPage } from "./features/auth/pages/RecuperarPage";
import { RestablecerPage } from "./features/auth/pages/RestablecerPage";
import { RutaProtegida } from "./features/auth/RutaProtegida";
import { SeleccionProvider } from "./features/catalogo/SeleccionProvider";
import { DashboardPage } from "./features/dashboard/DashboardPage";
import { AppLayout } from "./features/layout/AppLayout";
import { ACCESO } from "./lib/roles";
import { CargandoSeccion } from "./pages/CargandoSeccion";
import { NoEncontradoPage } from "./pages/NoEncontradoPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";
import { ApiError } from "./services/httpClient";

const UsuariosPage = lazy(() => import("./features/usuarios/UsuariosPage"));
const AuditoriaPage = lazy(() => import("./features/auditoria/AuditoriaPage"));
const RiegoPage = lazy(() => import("./features/riego/RiegoPage"));
const CargaNuevaPage = lazy(() => import("./features/riego/CargaNuevaPage"));
const CargaDetallePage = lazy(() => import("./features/riego/CargaDetallePage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // Sin reintentos para errores del cliente (4xx): solo red o servidor.
      retry: (intentos, error) =>
        !(error instanceof ApiError && error.status >= 400 && error.status < 500) && intentos < 2,
    },
    mutations: { retry: false },
  },
});

/** Zona autenticada: guard de sesión + selección de fundo y módulo compartida. */
function ZonaPrivada() {
  return (
    <RutaProtegida>
      <SeleccionProvider>
        <Outlet />
      </SeleccionProvider>
    </RutaProtegida>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <TooltipProvider delayDuration={300}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/recuperar" element={<RecuperarPage />} />
              <Route path="/restablecer" element={<RestablecerPage />} />

              <Route element={<ZonaPrivada />}>
                <Route path="/cambiar-password" element={<CambiarPasswordPage />} />
                <Route element={<AppLayout />}>
                  <Route index element={<DashboardPage />} />
                  <Route
                    path="generar"
                    element={
                      <RutaProtegida roles={ACCESO.generar}>
                        <PlaceholderPage
                          titulo="Generar"
                          descripcion="Genera los cronogramas de uno o más días con el modelo."
                          fase={3}
                          icono={<Sparkles />}
                          detalle="Elegirás la fecha y el número de días, verás la frescura de los datos de cada día y el resultado por día."
                        />
                      </RutaProtegida>
                    }
                  />
                  <Route
                    path="cronogramas/*"
                    element={
                      <RutaProtegida roles={ACCESO.cronogramas}>
                        <PlaceholderPage
                          titulo="Cronogramas"
                          descripcion="Listado y detalle de los cronogramas por fecha."
                          fase={3}
                          icono={<CalendarDays />}
                          detalle="El listado y el detalle en lectura llegan en la fase 3; la corrección, publicación y el “Visto” en la fase 4."
                        />
                      </RutaProtegida>
                    }
                  />
                  <Route
                    path="riego"
                    element={
                      <RutaProtegida roles={ACCESO.riego}>
                        <Suspense fallback={<CargandoSeccion />}>
                          <RiegoPage />
                        </Suspense>
                      </RutaProtegida>
                    }
                  />
                  <Route
                    path="riego/cargas/nueva"
                    element={
                      <RutaProtegida roles={ACCESO.cargaRiego}>
                        <Suspense fallback={<CargandoSeccion />}>
                          <CargaNuevaPage />
                        </Suspense>
                      </RutaProtegida>
                    }
                  />
                  <Route
                    path="riego/cargas/:id"
                    element={
                      <RutaProtegida roles={ACCESO.cargaRiego}>
                        <Suspense fallback={<CargandoSeccion />}>
                          <CargaDetallePage />
                        </Suspense>
                      </RutaProtegida>
                    }
                  />
                  <Route
                    path="datos"
                    element={
                      <RutaProtegida roles={ACCESO.datos}>
                        <PlaceholderPage
                          titulo="Datos de campo"
                          descripcion="Clima, suelo y planta de los últimos 14 días."
                          fase={5}
                          icono={<ChartLine />}
                          detalle="Agua aplicada vs propuesta por turno, MDS y crecimiento del tronco, humedad del suelo por profundidad y clima."
                        />
                      </RutaProtegida>
                    }
                  />
                  <Route
                    path="auditoria"
                    element={
                      <RutaProtegida roles={ACCESO.auditoria}>
                        <Suspense fallback={<CargandoSeccion />}>
                          <AuditoriaPage />
                        </Suspense>
                      </RutaProtegida>
                    }
                  />
                  <Route
                    path="usuarios"
                    element={
                      <RutaProtegida roles={ACCESO.usuarios}>
                        <Suspense fallback={<CargandoSeccion />}>
                          <UsuariosPage />
                        </Suspense>
                      </RutaProtegida>
                    }
                  />
                  <Route path="*" element={<NoEncontradoPage />} />
                </Route>
              </Route>
            </Routes>
          </TooltipProvider>
        </AuthProvider>
        <Toaster />
      </BrowserRouter>
    </QueryClientProvider>
  );
}
