import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { hoyLima, sumarDias } from "../../lib/fechas";
import type { Rol } from "../../lib/roles";
import { datosApi, ingestasApi, type Frescura, type FuenteFrescura, type IngestaCorrida } from "../../services/datos";
import { MODULO, seleccionCon, usuarioConRol } from "../../test/fabricas";
import {
  corridaColgada,
  corridasVisibles,
  detalleTurnos,
  diasAtraso,
  hayIngestaEnCurso,
  nombreFuente,
  progresoIngesta,
  resumirFrescura,
} from "./frescura";
import { DIAS_VENTANA_FRESCURA, PanelFrescura } from "./PanelFrescura";

let rol: Rol = "admin";
vi.mock("../auth/AuthProvider", () => ({ useUsuario: () => usuarioConRol(rol) }));
vi.mock("../catalogo/SeleccionProvider", () => ({ useSeleccion: () => seleccionCon() }));

const HOY = hoyLima();
const AYER = sumarDias(HOY, -1);

/** Fuente con la forma exacta de `FuenteFrescura` del backend. */
function fuente(nombre: string, extra: Partial<FuenteFrescura>): FuenteFrescura {
  return {
    fuente: nombre,
    nombre: nombre,
    ultima_fecha: null,
    estado: "naranja",
    informativa: false,
    huecos: [],
    detalle: null,
    por_turno: null,
    ...extra,
  };
}

const FRESCURA: Frescura = {
  modulo_id: MODULO.id,
  fecha: HOY,
  referencia: AYER,
  dias: DIAS_VENTANA_FRESCURA,
  fuentes: [
    fuente("weatherlink", { ultima_fecha: sumarDias(AYER, -7), estado: "naranja" }),
    fuente("riego_aplicado", { ultima_fecha: AYER, estado: "verde", huecos: [sumarDias(AYER, -3)] }),
    fuente("ndvi", { ultima_fecha: sumarDias(AYER, -5), estado: "informativo", informativa: true }),
    fuente("phytech_suelo", { ultima_fecha: null, estado: "naranja" }),
  ],
};

function corrida(id: number, estado: IngestaCorrida["estado"], extra: Partial<IngestaCorrida> = {}): IngestaCorrida {
  return {
    id,
    fuente: "weatherlink",
    disparo: "manual",
    usuario: "admin",
    fecha_programada: null,
    desde: null,
    hasta: null,
    inicio_at: new Date().toISOString(),
    latido_at: null,
    fin_at: null,
    duracion_ms: null,
    estado,
    filas_nuevas: 0,
    filas_actualizadas: 0,
    filas_omitidas: 0,
    conflictos: 0,
    errores: [],
    ...extra,
  };
}

beforeEach(() => {
  rol = "admin";
  vi.spyOn(datosApi, "frescura").mockResolvedValue(FRESCURA);
  vi.spyOn(ingestasApi, "listar").mockResolvedValue([
    corrida(1, "error", { fuente: "phytech_suelo", disparo: "programado", errores: [{ tipo: "credenciales", mensaje: "Credenciales rechazadas", status_code: 401, endpoint: "/v1/soil" }] }),
  ]);
});

afterEach(() => {
  vi.useRealTimers();
});

function montar() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <PanelFrescura />
    </QueryClientProvider>,
  );
}

describe("PanelFrescura", () => {
  it("muestra cada fuente con su última fecha completa, atraso y huecos", async () => {
    montar();
    const lista = await screen.findByRole("list", { name: "Frescura por fuente" });
    const filas = within(lista).getAllByRole("listitem");
    // Orden fijo: riego aplicado, WeatherLink, Phytech suelo, NDVI.
    expect(filas.map((f) => f.textContent)).toEqual([
      expect.stringContaining("Riego aplicado"),
      expect.stringContaining("WeatherLink"),
      expect.stringContaining("Phytech suelo"),
      expect.stringContaining("NDVI"),
    ]);
    expect(filas[0]).toHaveTextContent("Al día");
    expect(filas[0]).toHaveTextContent("Hueco:");
    expect(filas[1]).toHaveTextContent("Atrasado");
    expect(filas[1]).toHaveTextContent("faltan 7 días");
    expect(filas[2]).toHaveTextContent("Sin datos todavía");
    expect(filas[3]).toHaveTextContent("Informativo");
    expect(screen.getByText("2 fuentes atrasadas · 1 con huecos")).toBeInTheDocument();
    expect(datosApi.frescura).toHaveBeenCalledWith(MODULO.id, HOY, DIAS_VENTANA_FRESCURA, expect.anything());
  });

  it("el programador ve la frescura pero no «Actualizar ahora» ni las corridas", async () => {
    rol = "programador";
    montar();
    await screen.findByRole("list", { name: "Frescura por fuente" });
    expect(screen.queryByRole("button", { name: /Actualizar ahora/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Últimas corridas")).not.toBeInTheDocument();
    expect(ingestasApi.listar).not.toHaveBeenCalled();
  });

  it("el subgerente ve las corridas (sin secretos) pero no puede lanzar la ingesta", async () => {
    rol = "subgerente";
    montar();
    const corridas = await screen.findByRole("list", { name: "Últimas corridas de ingesta" });
    expect(within(corridas).getByText("Phytech suelo")).toBeInTheDocument();
    expect(within(corridas).getByText("Credenciales rechazadas (HTTP 401)")).toBeInTheDocument();
    expect(within(corridas).getByText(/Programada/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Actualizar ahora/ })).not.toBeInTheDocument();
  });

  it("«Actualizar ahora» lanza la ingesta, muestra el avance y al terminar refresca la frescura", async () => {
    rol = "encargado";
    const ejecutar = vi.spyOn(ingestasApi, "ejecutar").mockResolvedValue([corrida(10, "en_curso"), corrida(11, "en_curso", { fuente: "phytech_planta" })]);
    const listar = vi.mocked(ingestasApi.listar);
    montar();
    await screen.findByRole("list", { name: "Últimas corridas de ingesta" });
    listar.mockResolvedValue([corrida(10, "ok"), corrida(11, "en_curso", { fuente: "phytech_planta" })]);
    await userEvent.click(screen.getByRole("button", { name: /Actualizar ahora/ }));
    expect(ejecutar).toHaveBeenCalledWith({});
    expect(await screen.findByRole("progressbar", { name: "Avance de la actualización" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Actualizando/ })).toBeDisabled();
    expect(await screen.findByText("Actualizando: 1 de 2 fuentes terminadas")).toBeInTheDocument();

    const llamadasFrescura = vi.mocked(datosApi.frescura).mock.calls.length;
    listar.mockResolvedValue([corrida(10, "ok"), corrida(11, "ok", { fuente: "phytech_planta" })]);
    // El sondeo consulta GET /ingestas cada 2,5 s hasta que todas terminan.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 2700));
    });
    expect(await screen.findByRole("button", { name: /Actualizar ahora/ })).toBeEnabled();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(vi.mocked(datosApi.frescura).mock.calls.length).toBeGreaterThan(llamadasFrescura);
  }, 10_000);

  it("una corrida «en_curso» sin latido hace más de 10 min no bloquea «Actualizar ahora» ni deja el sondeo activo", async () => {
    const hace30min = new Date(Date.now() - 30 * 60_000).toISOString();
    // La colgada es la más vieja: antes ni siquiera estaba entre las 6 visibles.
    const recientes = Array.from({ length: 25 }, (_, i) =>
      corrida(100 + i, "ok", { fuente: "phytech_planta", inicio_at: new Date(Date.now() - (i + 1) * 60_000).toISOString() }),
    );
    vi.mocked(ingestasApi.listar).mockResolvedValue([...recientes, corrida(50, "en_curso", { inicio_at: hace30min })]);
    montar();
    const lista = await screen.findByRole("list", { name: "Últimas corridas de ingesta" });
    expect(within(lista).getByText("Sin terminar")).toBeInTheDocument();
    expect(within(lista).getByText(/Se cerrará al usar «Actualizar ahora»/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Actualizar ahora/ })).toBeEnabled();
    const llamadas = vi.mocked(ingestasApi.listar).mock.calls.length;
    await act(async () => {
      await new Promise((r) => setTimeout(r, 2700));
    });
    expect(vi.mocked(ingestasApi.listar).mock.calls.length).toBe(llamadas);
  }, 10_000);

  it("una corrida larga con latido reciente mantiene Actualizar ahora deshabilitado", async () => {
    vi.mocked(ingestasApi.listar).mockResolvedValue([corrida(50, "en_curso", {
      inicio_at: new Date(Date.now() - 5 * 3600_000).toISOString(),
      latido_at: new Date(Date.now() - 60_000).toISOString(),
    })]);
    montar();
    const lista = await screen.findByRole("list", { name: "Últimas corridas de ingesta" });
    expect(within(lista).getByText("En curso")).toBeInTheDocument();
    expect(within(lista).queryByText("Sin terminar")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Actualizando/ })).toBeDisabled();
  });

  it("en riego, la línea por turno dice solo lo que difiere: el hueco propio de TE05", async () => {
    const turno = (codigo: string, huecos: string[]) => ({
      turno_id: Number(codigo.slice(2)),
      turno_codigo: codigo,
      ultima_fecha: "2026-11-04",
      huecos,
    });
    vi.mocked(datosApi.frescura).mockResolvedValue({
      ...FRESCURA,
      fuentes: [
        fuente("riego_aplicado", {
          ultima_fecha: "2026-11-04",
          huecos: ["2026-11-01", "2026-11-03"],
          por_turno: [
            turno("TE01", ["2026-11-01"]),
            turno("TE02", ["2026-11-01"]),
            turno("TE03", ["2026-11-01"]),
            turno("TE04", ["2026-11-01"]),
            turno("TE05", ["2026-11-01", "2026-11-03"]),
          ],
        }),
      ],
    });
    montar();
    const lista = await screen.findByRole("list", { name: "Frescura por fuente" });
    expect(within(lista).getByText("TE05: falta mar 03/11")).toBeInTheDocument();
    expect(lista).not.toHaveTextContent("TE01");
  });
});

describe("cálculos de frescura e ingestas", () => {
  it("resume atrasadas (sin contar informativas) y huecos", () => {
    expect(resumirFrescura(FRESCURA.fuentes)).toEqual({ atrasadas: 2, conHuecos: 1, alDia: false });
    expect(resumirFrescura([fuente("weatherlink", { ultima_fecha: AYER, estado: "verde" })]).alDia).toBe(true);
  });

  it("calcula los días de atraso respecto de ayer", () => {
    expect(diasAtraso(fuente("x", { ultima_fecha: "2026-11-04", estado: "naranja" }), "2026-11-07")).toBe(3);
    expect(diasAtraso(fuente("x", { ultima_fecha: "2026-11-07", estado: "verde" }), "2026-11-07")).toBe(0);
    expect(diasAtraso(fuente("x", { ultima_fecha: null, estado: "naranja" }), "2026-11-07")).toBeNull();
  });

  it("sigue el avance de las corridas lanzadas y da el resultado global", () => {
    expect(progresoIngesta([1, 2], [corrida(1, "ok"), corrida(2, "en_curso")])).toMatchObject({ terminadas: 1, completo: false });
    expect(progresoIngesta([1, 2], [corrida(1, "ok"), corrida(2, "ok")])).toMatchObject({ completo: true, resultado: "ok" });
    expect(progresoIngesta([1, 2], [corrida(1, "ok"), corrida(2, "error")])).toMatchObject({ resultado: "parcial" });
    expect(progresoIngesta([1], [corrida(1, "error")])).toMatchObject({ resultado: "error" });
    // Una corrida que ya no aparece no deja el sondeo colgado si no queda nada en curso.
    expect(progresoIngesta([1, 99], [corrida(1, "ok")])).toMatchObject({ completo: true });
    expect(progresoIngesta([1, 99], [corrida(1, "ok"), corrida(5, "en_curso")])).toMatchObject({ completo: false });
    expect(progresoIngesta([], [])).toMatchObject({ completo: false });
    // Una corrida lanzada que quedó colgada (> 10 min sin latido) termina el seguimiento como error.
    const colgada = corrida(3, "en_curso", { inicio_at: new Date(Date.now() - 4 * 3600_000).toISOString() });
    expect(progresoIngesta([3], [colgada])).toMatchObject({ completo: true, resultado: "error" });
  });

  it("usa el latido, el inicio como respaldo y el límite estricto de 10 minutos", () => {
    const ahora = new Date("2026-11-08T12:00:00-05:00");
    const hace = (min: number) => new Date(ahora.getTime() - min * 60_000).toISOString();
    const viva = corrida(1, "en_curso", { inicio_at: hace(600), latido_at: hace(2) });
    expect(corridaColgada(viva, ahora)).toBe(false);
    expect(hayIngestaEnCurso([viva], ahora)).toBe(true);
    expect(corridaColgada(corrida(1, "en_curso", { latido_at: hace(10) }), ahora)).toBe(false);
    expect(corridaColgada(corrida(1, "en_curso", { latido_at: hace(10.01) }), ahora)).toBe(true);
    expect(corridaColgada(corrida(1, "en_curso", { inicio_at: hace(10) }), ahora)).toBe(false);
    expect(corridaColgada(corrida(1, "en_curso", { inicio_at: hace(11) }), ahora)).toBe(true);
    expect(corridaColgada(corrida(1, "error", { latido_at: hace(11) }), ahora)).toBe(false);
    expect(hayIngestaEnCurso([corrida(1, "en_curso", { inicio_at: hace(11) })], ahora)).toBe(false);
  });

  it("muestra primero las corridas en curso aunque sean viejas", () => {
    const lista = [corrida(3, "ok"), corrida(2, "ok"), corrida(1, "en_curso")];
    expect(corridasVisibles(lista, 2).map((c) => c.id)).toEqual([1, 3]);
  });

  it("nombra en español las corridas de la carga histórica y del reproceso", () => {
    expect(nombreFuente("historico_meteo")).toBe("Carga histórica: clima");
    expect(nombreFuente("historico_phytech")).toBe("Carga histórica: Phytech");
    expect(nombreFuente("historico_ndvi")).toBe("Carga histórica: NDVI");
    expect(nombreFuente("historico_riego")).toBe("Carga histórica: riego");
    expect(nombreFuente("reprocesar_weatherlink")).toBe("Reproceso WeatherLink");
  });

  it("detalle por turno: otra última fecha o huecos que no comparten todos", () => {
    const t = (codigo: string, ultima: string | null, huecos: string[] = []) => ({
      turno_id: 1,
      turno_codigo: codigo,
      ultima_fecha: ultima,
      huecos,
    });
    expect(detalleTurnos({ por_turno: null })).toEqual([]);
    expect(
      detalleTurnos({ por_turno: [t("TE01", "2026-11-04", ["2026-11-01"]), t("TE02", "2026-11-04", ["2026-11-01"])] }),
    ).toEqual([]);
    expect(
      detalleTurnos({
        por_turno: [t("TE01", "2026-11-07"), t("TE02", "2026-11-07"), t("TE03", "2026-11-04", ["2026-11-02"]), t("TE04", null)],
      }),
    ).toEqual(["TE03: hasta mié 04/11 · falta lun 02/11", "TE04: sin datos"]);
  });
});
