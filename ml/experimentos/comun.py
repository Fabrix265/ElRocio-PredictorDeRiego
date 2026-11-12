"""Marco común de los experimentos (separado del pipeline en uso).

Nada de este paquete escribe en ``ml/models/`` ni cambia ``config/pipeline.yaml``:
solo lee las tablas del paso 2 (``data/processed``) y reutiliza las funciones de
``riego_ml`` tal como están. Los resultados van a ``ml/reports/experimentos/``.

Protocolo de evaluación
-----------------------
* **Períodos de desarrollo** (5 semestres, 2023-03 a 2025-09): en cada uno, cada
  candidato aprende con TODO lo anterior (menos 7 días de separación) y se mide en
  ese semestre. El ganador se elige por el promedio de estos 5 períodos.
* **Examen final** (2025-09-23 a 2026-11-04, el mismo test del modelo en uso):
  se aprende con todo lo anterior al 2025-09-15 y se informa, nunca se usa para
  elegir.
* El **modelo en uso** se reproduce con la misma receta en cada período: así la
  comparación es justa (mismos datos de aprendizaje para todos).
"""

from __future__ import annotations

import logging
import sys
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

RAIZ_ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ_ML / "src"))
for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        _flujo.reconfigure(encoding="utf-8")

from riego_ml.config import load_config  # noqa: E402
from riego_ml.dataset.preparar import cargar_dataset  # noqa: E402
from riego_ml.modeling import metricas  # noqa: E402

GAP = pd.Timedelta(days=7)
MAX_CICLOS = 5
SEED = 42

PERIODOS_DEV = [
    ("dev1", "2023-03-16", "2023-09-15"),
    ("dev2", "2023-09-16", "2024-03-15"),
    ("dev3", "2024-03-16", "2024-09-15"),
    ("dev4", "2024-09-16", "2025-03-15"),
    ("dev5", "2025-03-16", "2025-09-15"),
]
PERIODO_FINAL = ("final", "2025-09-23", None)
FRANJAS = [0, 360, 720, 1080, 1440]  # 00-06, 06-12, 12-18, 18-24
NOMBRES_FRANJA = ["00-06", "06-12", "12-18", "18-24"]


@dataclass
class Periodo:
    nombre: str
    inicio: pd.Timestamp
    fin: pd.Timestamp | None

    @property
    def fin_train(self) -> pd.Timestamp:
        return self.inicio - GAP - pd.Timedelta(days=1)

    def mascaras(self, fechas: pd.Series) -> tuple[pd.Series, pd.Series]:
        train = fechas <= self.fin_train
        evalua = fechas >= self.inicio
        if self.fin is not None:
            evalua &= fechas <= self.fin
        return train, evalua

    @property
    def es_final(self) -> bool:
        return self.nombre == "final"


def periodos(incluir_final: bool = True, solo: list[str] | None = None) -> list[Periodo]:
    lista = [*PERIODOS_DEV, *( [PERIODO_FINAL] if incluir_final else [])]
    out = [Periodo(n, pd.Timestamp(i), pd.Timestamp(f) if f else None) for n, i, f in lista]
    return [p for p in out if solo is None or p.nombre in solo]


@dataclass
class Datos:
    turno_dia: pd.DataFrame
    ciclos: pd.DataFrame          # ciclos con n_ciclos <= MAX_CICLOS (los que se modelan)
    ciclos_hist: pd.DataFrame     # todos los ciclos (historia para features)
    f_turno: list[str]
    f_ciclo: list[str]
    categoricas: list[str]
    config: Any = None
    extra: dict[str, Any] = field(default_factory=dict)


def cargar_datos() -> Datos:
    config = load_config()
    ds = cargar_dataset(config.rutas.processed_dir)
    td = ds.turno_dia.copy()
    td["Fecha"] = pd.to_datetime(td["Fecha"])
    td["n_ciclos_clase"] = td["n_ciclos"].clip(upper=MAX_CICLOS).astype(int)
    ci_hist = ds.ciclos.copy()
    ci_hist["Fecha"] = pd.to_datetime(ci_hist["Fecha"])
    ci = ci_hist[ci_hist["n_ciclos"] <= MAX_CICLOS].copy()
    # Columnas auxiliares (NO son features: sirven para targets alternativos y escenarios)
    primer = ci[ci["Ciclo"] == 1].set_index(["Fecha", "Fundo", "Modulo", "Turno"])["inicio_min"]
    ci["inicio_ciclo1_real"] = pd.MultiIndex.from_frame(ci[["Fecha", "Fundo", "Modulo", "Turno"]]).map(primer)
    ci["inicio_modulo_real"] = ci.groupby(["Fecha", "Fundo", "Modulo"])["inicio_min"].transform("min")
    ci = ci.sort_values(["Fecha", "Turno", "Ciclo"]).reset_index(drop=True)
    td = td.sort_values(["Fecha", "Turno"]).reset_index(drop=True)
    cols = ds.columnas
    return Datos(td, ci, ci_hist, list(cols["features_turno"]), list(cols["features_ciclo"]),
                 list(cols["categoricas"]), config)


def mascara_eval(df: pd.DataFrame) -> pd.Series:
    """Días incompletos no se evalúan (igual que el pipeline en uso)."""
    return df["dia_incompleto"].fillna(0) == 0


# --------------------------------------------------------------------------- #
# Métricas
# --------------------------------------------------------------------------- #
def franja(minutos) -> np.ndarray:
    m = np.clip(np.asarray(minutos, dtype=float), 0, 1439)
    return np.digitize(m, FRANJAS[1:-1])


def metricas_n_ciclos(real, pred, prev) -> dict[str, float]:
    real = np.asarray(real).astype(int)
    pred = np.asarray(pred).astype(int)
    prev = np.asarray(prev, dtype=float)
    base = metricas.clasificacion(real, pred, list(range(1, MAX_CICLOS + 1)))
    base.pop("confusion", None)
    hay_prev = np.isfinite(prev)
    cambio = hay_prev & (real != prev)
    sin_cambio = hay_prev & (real == prev)
    propone = hay_prev & (pred != prev)
    altos = real >= 4
    base.update({
        "acierto_sin_cambio": float(np.mean(pred[sin_cambio] == real[sin_cambio])) if sin_cambio.any() else np.nan,
        "acierto_con_cambio": float(np.mean(pred[cambio] == real[cambio])) if cambio.any() else np.nan,
        "dias_con_cambio": int(cambio.sum()),
        "propone_cambio": float(np.mean(propone[hay_prev])) if hay_prev.any() else np.nan,
        # De las veces que propone cambiar, ¿cuántas acierta el número exacto?
        "precision_cambio": float(np.mean(pred[propone] == real[propone])) if propone.any() else np.nan,
        "acierto_4mas": float(np.mean(pred[altos] == real[altos])) if altos.any() else np.nan,
    })
    return base


def metricas_reg(real, pred) -> dict[str, float]:
    out = metricas.regresion(real, pred)
    for k in ("pearson_r", "kge", "pbias_pct", "willmott_d"):
        out.pop(k, None)
    return out


def metricas_inicio(real, pred) -> dict[str, float]:
    out = metricas_reg(real, pred)
    err = np.abs(np.asarray(pred, float) - np.asarray(real, float))
    out["dentro_1h"] = float(np.mean(err <= 60))
    out["dentro_2h"] = float(np.mean(err <= 120))
    out["franja_ok"] = float(np.mean(franja(real) == franja(pred)))
    return out


def metricas_rango(real, bajo, alto) -> dict[str, float]:
    real = np.asarray(real, float)
    return {"n": int(real.size), "cobertura": float(np.mean((real >= bajo) & (real <= alto))),
            "ancho_medio": float(np.mean(np.asarray(alto) - np.asarray(bajo)))}


# --------------------------------------------------------------------------- #
# Ejecución
# --------------------------------------------------------------------------- #
def ajustar(estimador, X, y, **fit_params):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return estimador.fit(X, y, **fit_params)


def logger(nombre: str = "experimentos") -> logging.Logger:
    log = logging.getLogger(nombre)
    if not log.handlers:
        h = logging.StreamHandler(sys.stdout)
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        log.addHandler(h)
        log.setLevel(logging.INFO)
    return log


def carpeta_resultados(nombre: str | None = None) -> Path:
    base = RAIZ_ML / "reports" / "experimentos"
    carpeta = base / (nombre or "ultimo")
    (carpeta / "datos").mkdir(parents=True, exist_ok=True)
    return carpeta


@dataclass
class Candidato:
    """Un candidato del concurso.

    ``clave``: candidatos con la misma clave comparten el modelo entrenado y solo
    difieren en ``ajustes`` (p. ej. el umbral), así no se entrena dos veces lo mismo.
    ``grupo``: "modelo" compite; "escenario" usa información que NO existe a la
    medianoche (se informa aparte, nunca se elige).
    """

    nombre: str
    crear: Callable[[], Any]
    descripcion: str
    clave: str | None = None
    ajustes: dict[str, Any] = field(default_factory=dict)
    grupo: str = "modelo"

    def __post_init__(self):
        self.clave = self.clave or self.nombre

    def entrenar(self, X, y):
        modelo = ajustar(self.crear(), X, y)
        return self.aplicar(modelo)

    def aplicar(self, modelo):
        for k, v in self.ajustes.items():
            setattr(modelo, k, v)
        return modelo


def correr(
    registro: list[Candidato],
    preparar: Callable[[Periodo], tuple[pd.DataFrame, Any, pd.DataFrame, Any]],
    medir: Callable[[Any, np.ndarray, pd.DataFrame], dict[str, float]],
    lista_periodos: list[Periodo],
    log: logging.Logger,
    target: str,
) -> tuple[pd.DataFrame, dict[str, np.ndarray]]:
    """Entrena y mide cada candidato en cada período. Devuelve métricas y predicciones del examen final."""
    filas, pred_final = [], {}
    for p in lista_periodos:
        Xtr, ytr, Xev, yev = preparar(p)
        cache: dict[str, Any] = {}
        for c in registro:
            t0 = time.time()
            try:
                if c.clave not in cache:
                    cache[c.clave] = ajustar(c.crear(), Xtr, ytr)
                modelo = c.aplicar(cache[c.clave])
                pred = np.asarray(modelo.predict(Xev))
            except Exception as exc:  # noqa: BLE001 - un candidato que falla no frena al resto
                log.warning("  %s/%s/%s falló: %r", target, p.nombre, c.nombre, exc)
                continue
            seg = round(time.time() - t0, 1)
            valores = medir(yev, pred, Xev)
            filas.append({"target": target, "candidato": c.nombre, "grupo": c.grupo, "periodo": p.nombre,
                          "segundos": seg, **valores})
            if p.es_final:
                pred_final[c.nombre] = pred
            clave = next((k for k in ("accuracy", "mae") if k in valores), None)
            log.info("  %-10s %-6s %-40s %s=%.4f (%.0fs)", target, p.nombre, c.nombre, clave,
                     valores.get(clave, np.nan), seg)
    return pd.DataFrame(filas), pred_final


def buscar_hiper(
    nombre: str,
    crear: Callable[[dict[str, Any]], Any],
    espacio: dict[str, list],
    preparar: Callable[[Periodo], tuple],
    medir: Callable[[Any, np.ndarray, pd.DataFrame], dict[str, float]],
    clave: str,
    mayor_mejor: bool,
    n_iter: int,
    log: logging.Logger,
    en: tuple[str, ...] = ("dev3", "dev4", "dev5"),
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Búsqueda aleatoria de hiperparámetros evaluada en períodos de desarrollo (nunca el examen final)."""
    rng = np.random.default_rng(SEED)
    combos = [{k: v[rng.integers(len(v))] for k, v in espacio.items()} for _ in range(n_iter)]
    lista = periodos(incluir_final=False, solo=list(en))
    datos = {p.nombre: preparar(p) for p in lista}
    filas = []
    for i, params in enumerate(combos):
        puntajes = []
        for p in lista:
            Xtr, ytr, Xev, yev = datos[p.nombre]
            pred = ajustar(crear(params), Xtr, ytr).predict(Xev)
            puntajes.append(medir(yev, np.asarray(pred), Xev)[clave])
        filas.append({"combo": i, **{k: str(v) for k, v in params.items()}, clave: float(np.mean(puntajes))})
        log.info("  ajuste %s %2d/%d %s=%.4f %s", nombre, i + 1, n_iter, clave, np.mean(puntajes), params)
    tabla = pd.DataFrame(filas).sort_values(clave, ascending=not mayor_mejor)
    return combos[int(tabla.iloc[0]["combo"])], tabla


def resumir(resultados: pd.DataFrame, metricas_cols: list[str], clave: str, mayor_mejor: bool,
            referencia: str) -> pd.DataFrame:
    """Promedio en desarrollo + examen final, por candidato, con la referencia (modelo en uso)."""
    dev = resultados[resultados["periodo"].str.startswith("dev")]
    fin = resultados[resultados["periodo"] == "final"]
    grupo = resultados.groupby("candidato")["grupo"].first()
    prom = dev.groupby("candidato")[metricas_cols].mean().add_suffix("_dev")
    std = dev.groupby("candidato")[clave].std().rename(f"{clave}_dev_std")
    final = fin.set_index("candidato")[metricas_cols].add_suffix("_final")
    tabla = prom.join(std).join(final, how="outer").join(grupo)
    # Cuántos períodos de desarrollo gana a la referencia
    if referencia in dev["candidato"].values:
        ref = dev[dev["candidato"] == referencia].set_index("periodo")[clave]
        piv = dev.pivot_table(index="candidato", columns="periodo", values=clave)
        mejor = piv.gt(ref, axis=1) if mayor_mejor else piv.lt(ref, axis=1)
        tabla["gana_a_actual_dev"] = mejor.sum(axis=1).astype(int).astype(str) + f"/{piv.shape[1]}"
    orden = f"{clave}_dev"
    return tabla.sort_values(orden, ascending=not mayor_mejor)
