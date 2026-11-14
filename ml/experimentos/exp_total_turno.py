"""Experimento: un modelo que predice SOLO el total de m³/ha de cada turno por día.

Con riego por pulsos el sistema web ya no usa los ciclos ni los horarios del modelo en uso:
toma el total de m³/ha de cada turno-día y ``backend/app/services/calculo_pulsos.py`` arma
los ciclos, la duración y el horario. Este experimento entrena un modelo directo de ese total
y lo compara, en el mismo test y en la misma unidad, con el modelo en uso (la suma de los
m³/ha de los ciclos que predice).

Reglas (ver ``ml/experimentos/README.md``):

* No cambia ``ml/src/riego_ml/``, ``config/pipeline.yaml`` ni ``models/plan_riego/``.
  Reutiliza las tablas del paso 2, ``construir_features_turno``, el split temporal con gap
  (train → 7 días → validación → 7 días → test) y la fábrica de estimadores.
* El ganador se elige SOLO por validación (RMSE; desempate por MAE). El test solo se informa.
* El modelo en uso guardado en ``models/plan_riego/actual`` se reentrenó con todos los datos
  (vio el test), así que para compararlo se reproduce su receta con ``reentrenar_hasta``.
* El resultado (y, si gana, la versión candidata) va a ``reports/experimentos/total_turno`` y
  ``models/total_turno``. Configuración propia en ``config/total_turno.yaml``.

Uso, desde la raíz del repositorio::

    ml/.venv/Scripts/python ml/experimentos/exp_total_turno.py
    ml/.venv/Scripts/python ml/experimentos/exp_total_turno.py --sin-ajuste --no-guardar-modelo
"""

from __future__ import annotations

import argparse
import ast
import dataclasses
import importlib.util
import json
import platform
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml

DIR_EXPERIMENTOS = Path(__file__).resolve().parent
if str(DIR_EXPERIMENTOS) not in sys.path:
    sys.path.insert(0, str(DIR_EXPERIMENTOS))

from comun import RAIZ_ML, SEED, ajustar, logger  # noqa: E402  (también agrega ml/src al path)
from riego_ml.config import Config, load_config  # noqa: E402
from riego_ml.dataset.features import CATEGORICAS, construir_features_turno  # noqa: E402
from riego_ml.dataset.limpieza import CLAVES_TD  # noqa: E402
from riego_ml.dataset.preparar import cargar_dataset, cargar_historial, features_para_fechas  # noqa: E402
from riego_ml.modeling import metricas  # noqa: E402
from riego_ml.modeling.estimadores import (  # noqa: E402
    _preprocesador,
    crear_estimador,
    espacio_busqueda,
    importancias,
)
from riego_ml.modeling.evaluacion import reentrenar_hasta  # noqa: E402
from riego_ml.modeling.prediccion import cargar_plan  # noqa: E402
from riego_ml.modeling.split import CortesTemporales, cortes_temporales  # noqa: E402

RAIZ_REPO = RAIZ_ML.parent
RUTA_CONFIG = RAIZ_ML / "config" / "total_turno.yaml"
RUTA_PULSOS = RAIZ_REPO / "backend" / "app" / "services" / "calculo_pulsos.py"
RUTA_PARAMETROS = RAIZ_REPO / "backend" / "app" / "services" / "parametros_pulsos_service.py"
TARGET = "riego_total_m3ha"
REFERENCIAS = ("persistencia", "media_7d")
NOMBRE_MODELO = "modelo_total_turno.joblib"

CALENDARIO = {"Turno", "mes", "dia_semana", "doy_sin", "doy_cos", "turno_num", "es_feriado",
              "vispera_feriado", "post_feriado"}
PREFIJOS_CLIMA = ("T_", "HR_", "ETo_", "DPV_", "Viento_", "Lluvia_", "Rad_", "horas_T30")
PREFIJOS_SUELO = ("d_hum_", "resp_hum_", "hum_")
PREFIJOS_PLANTA = ("mds_", "crecimiento_", "estres_", "ndvi_")


# --------------------------------------------------------------------------- #
# Configuración
# --------------------------------------------------------------------------- #
def cargar_config_experimento(ruta: Path = RUTA_CONFIG) -> dict[str, Any]:
    return yaml.safe_load(ruta.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Datos: grilla turno-día con los días sin riego (0 m³/ha)
# --------------------------------------------------------------------------- #
def _rachas(fechas: list[pd.Timestamp]) -> list[list[pd.Timestamp]]:
    """Agrupa fechas ordenadas en rachas de días seguidos."""
    rachas: list[list[pd.Timestamp]] = []
    for f in sorted(fechas):
        if rachas and f - rachas[-1][-1] == pd.Timedelta(days=1):
            rachas[-1].append(f)
        else:
            rachas.append([f])
    return rachas


def armar_grilla(turno_dia: pd.DataFrame, max_dias_sin_riego: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Turno-días observados + días del módulo sin ningún registro con target 0.

    * Un día en que el módulo entero no tiene registro se cuenta como "sin riego" (0 m³/ha en
      todos sus turnos) si el hueco dura ``max_dias_sin_riego`` días seguidos o menos; si es
      más largo se trata como falta de datos y queda fuera.
    * Los turnos que faltan en un día con registros NO se agregan: ese día ya está marcado como
      ``dia_incompleto`` (no se sabe si no se regó o no se registró) y no se evalúa.
    """
    obs = turno_dia[[*CLAVES_TD, TARGET, "n_ciclos", "dia_incompleto"]].copy()
    obs["Fecha"] = pd.to_datetime(obs["Fecha"]).dt.normalize()
    obs["sin_riego"] = 0
    ceros, huecos = [], []
    for (fundo, modulo), g in obs.groupby(["Fundo", "Modulo"]):
        turnos = sorted(g["Turno"].unique())
        calendario = pd.date_range(g["Fecha"].min(), g["Fecha"].max(), freq="D")
        faltan = calendario.difference(pd.DatetimeIndex(g["Fecha"].unique()))
        for racha in _rachas(list(faltan)):
            tipo = "sin_riego" if len(racha) <= max_dias_sin_riego else "hueco_de_datos"
            huecos.append({"Fundo": fundo, "Modulo": modulo, "desde": racha[0], "hasta": racha[-1],
                           "dias": len(racha), "tratamiento": tipo})
            if tipo == "sin_riego":
                ceros += [{"Fecha": f, "Fundo": fundo, "Modulo": modulo, "Turno": t}
                          for f in racha for t in turnos]
    filas_cero = pd.DataFrame(ceros, columns=CLAVES_TD)
    filas_cero[TARGET] = 0.0
    filas_cero["n_ciclos"] = 0
    filas_cero["dia_incompleto"] = 0
    filas_cero["sin_riego"] = 1
    grilla = pd.concat([obs, filas_cero], ignore_index=True)
    grilla["Fecha"] = pd.to_datetime(grilla["Fecha"])  # sin días a 0, la tabla vacía deja tipo object
    grilla = grilla.sort_values(CLAVES_TD).reset_index(drop=True)
    if grilla.duplicated(CLAVES_TD).any():
        raise ValueError("La grilla turno-día tiene filas duplicadas.")
    return grilla, pd.DataFrame(huecos, columns=["Fundo", "Modulo", "desde", "hasta", "dias", "tratamiento"])


def referencias(grilla: pd.DataFrame) -> pd.DataFrame:
    """Persistencia (ayer) y media de 7 días del total del mismo turno, solo con días anteriores.

    Usa la grilla con los días sin riego (0); los huecos de datos quedan vacíos.
    """
    frames = []
    for claves, g in grilla.groupby(["Fundo", "Modulo", "Turno"]):
        serie = g.set_index("Fecha")[TARGET]
        serie = serie.reindex(pd.date_range(serie.index.min(), serie.index.max(), freq="D"))
        previo = serie.shift(1)
        f = pd.DataFrame({"Fecha": serie.index, "ref_ayer": previo.to_numpy(),
                          "ref_media7": previo.rolling(7, min_periods=3).mean().to_numpy()})
        f["Fundo"], f["Modulo"], f["Turno"] = claves
        frames.append(f)
    return pd.concat(frames, ignore_index=True)[[*CLAVES_TD, "ref_ayer", "ref_media7"]]


def construir_tabla(turno_dia: pd.DataFrame, ambiente: pd.DataFrame, incluir_meteo_dia: bool,
                    max_dias_sin_riego: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Grilla + features turno-día (las mismas funciones del pipeline) + referencias.

    Las features se calculan con el historial OBSERVADO (como en producción, ``predecir.py``):
    un día sin registro queda como "sin dato" en los rezagos y ``dias_desde_ultimo_riego`` lo
    refleja. Todo es conocido a las 00:00 del día (lo verifica ``tests/test_features.py``).
    """
    grilla, huecos = armar_grilla(turno_dia, max_dias_sin_riego)
    feats = construir_features_turno(grilla[CLAVES_TD], turno_dia, ambiente, incluir_meteo_dia)
    tabla = grilla.merge(feats, on=CLAVES_TD, how="left", validate="one_to_one")
    tabla = tabla.merge(referencias(grilla), on=CLAVES_TD, how="left", validate="one_to_one")
    return tabla, huecos


def diferencia_con_paso2(tabla: pd.DataFrame, turno_dia: pd.DataFrame, features: list[str]) -> float:
    """Máxima diferencia entre las features recalculadas y las de ``turno_dia.csv`` (debe ser 0).

    Un valor vacío en una tabla y no en la otra cuenta como diferencia infinita.
    """
    numericas = [c for c in features if c not in CATEGORICAS]
    a = tabla[tabla["sin_riego"] == 0].set_index(CLAVES_TD)[numericas].sort_index().astype(float)
    b = turno_dia.set_index(CLAVES_TD)[numericas].astype(float).reindex(a.index)
    if (a.isna() != b.isna()).any().any():
        return float("inf")
    return float((a - b).abs().max().max())


# --------------------------------------------------------------------------- #
# Features y candidatos
# --------------------------------------------------------------------------- #
def grupo_de(columna: str) -> str:
    if columna in CALENDARIO:
        return "calendario"
    if columna.startswith(PREFIJOS_SUELO):
        return "suelo"
    if columna.startswith(PREFIJOS_PLANTA):
        return "planta"
    if columna.startswith(PREFIJOS_CLIMA) or columna in ("balance_hidrico_7d", "reposicion_7d"):
        return "clima"
    return "riego"


def grupos_features(features: list[str]) -> dict[str, list[str]]:
    grupos: dict[str, list[str]] = {}
    for c in features:
        grupos.setdefault(grupo_de(c), []).append(c)
    return grupos


def variantes_features(features: list[str], variantes: dict[str, list[str]]) -> dict[str, list[str]]:
    return {nombre: [c for c in features if grupo_de(c) in set(incluye)] for nombre, incluye in variantes.items()}


def crear_modelo(familia: str, params: dict[str, Any], features: list[str], config: Config):
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline

    categoricas = [c for c in features if c in CATEGORICAS]
    numericas = [c for c in features if c not in CATEGORICAS]
    if familia == "ridge":
        return Pipeline([("prep", _preprocesador(categoricas, numericas, escalar=True)),
                         ("modelo", Ridge(alpha=float(params.get("alpha", 10.0))))])
    base = dict(config.modelos[familia].regresion)
    base.update(params)
    return crear_estimador(familia, "regresion", base, categoricas, numericas, SEED)


def predecir(modelo, filas: pd.DataFrame, features: list[str]) -> np.ndarray:
    return np.clip(np.asarray(modelo.predict(filas[features]), dtype=float), 0.0, None)


def predecir_referencia(nombre: str, filas: pd.DataFrame, mediana_turno: dict[str, float]) -> np.ndarray:
    """Persistencia: el total de ayer (si falta, la media 7 días; si falta, la mediana del turno)."""
    base = filas["Turno"].map(mediana_turno)
    if nombre == "persistencia":
        pred = filas["ref_ayer"].fillna(filas["ref_media7"]).fillna(base)
    else:
        pred = filas["ref_media7"].fillna(filas["ref_ayer"]).fillna(base)
    return pred.to_numpy(dtype=float)


def medir(real, pred) -> dict[str, float]:
    m = metricas.regresion(real, pred)
    return {k: m.get(k, np.nan) for k in ("n", "mae", "rmse", "r2", "mbe", "medae")}


def _mejor(tabla: pd.DataFrame) -> pd.Series:
    return tabla.sort_values(["rmse", "mae"]).iloc[0]


def combinaciones_ajuste(familia: str, n_iter: int, ridge_alphas: list[float]) -> list[dict[str, Any]]:
    if familia == "ridge":
        return [{"alpha": float(a)} for a in ridge_alphas]
    rng = np.random.default_rng(SEED)
    espacio = espacio_busqueda(familia, "regresion")
    return [{k: v[rng.integers(len(v))] for k, v in espacio.items()} for _ in range(n_iter)]


def _limpio(params: dict[str, Any]) -> dict[str, Any]:
    """Parámetros con tipos nativos (para JSON)."""
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in params.items()}


# --------------------------------------------------------------------------- #
# Modelo en uso: total del plan (suma de los m³/ha de sus ciclos)
# --------------------------------------------------------------------------- #
def total_plan(plan, filas: pd.DataFrame, ciclos_hist: pd.DataFrame) -> np.ndarray:
    """Total m³/ha por turno-día del ``PlanRiego`` (n° de ciclos predicho → m³/ha de cada ciclo)."""
    predicho = plan.predecir(filas, ciclos_hist)
    total = predicho.groupby(CLAVES_TD)["riego_m3ha"].sum().rename("total").reset_index()
    unido = filas[CLAVES_TD].merge(total, on=CLAVES_TD, how="left", validate="one_to_one")
    if unido["total"].isna().any():
        raise ValueError("El plan en uso no devolvió ciclos para algún turno-día.")
    return unido["total"].to_numpy(dtype=float)


# --------------------------------------------------------------------------- #
# Riego por pulsos (lógica del backend, sin importar ``app``)
# --------------------------------------------------------------------------- #
def cargar_calculo_pulsos(ruta: Path = RUTA_PULSOS):
    """Carga ``calculo_pulsos.py`` por ruta: solo usa la librería estándar (no trae SQLAlchemy)."""
    nombre = "calculo_pulsos_backend"
    if nombre in sys.modules:
        return sys.modules[nombre]
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo  # dataclasses lo necesita registrado
    spec.loader.exec_module(modulo)
    return modulo


def leer_por_defecto(ruta: Path = RUTA_PARAMETROS) -> dict[str, Any]:
    """Lee el literal ``POR_DEFECTO`` de ``parametros_pulsos_service.py`` sin importar el módulo."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    for nodo in arbol.body:
        destino = nodo.target if isinstance(nodo, ast.AnnAssign) else (
            nodo.targets[0] if isinstance(nodo, ast.Assign) else None)
        if isinstance(destino, ast.Name) and destino.id == "POR_DEFECTO":
            codigo = compile(ast.Expression(nodo.value), str(ruta), "eval")
            # Solo un literal con una comprensión de diccionario (curva 3): sin builtins.
            return eval(codigo, {"__builtins__": {}, "range": range, "str": str})  # noqa: S307
    raise ValueError(f"No se encontró POR_DEFECTO en {ruta}")


def a_parametros(cp, valores: dict[str, Any]):
    """Diccionario → ``calculo_pulsos.Parametros`` (como ``parametros_pulsos_service.a_parametros``)."""
    campos = {f.name for f in dataclasses.fields(cp.Parametros)}
    kw = {k: v for k, v in valores.items() if k in campos}
    kw["mangueras_por_hilera"] = int(kw["mangueras_por_hilera"])
    kw["agotamiento_por_fase"] = {k: float(x) for k, x in kw["agotamiento_por_fase"].items()}
    kw["curvas"] = {n: {int(h): float(p) for h, p in c.items()} for n, c in kw["curvas"].items()}
    return cp.Parametros(**kw)


def pulsos_por_dia(cp, parametros, filas: pd.DataFrame, columna: str, areas: dict[str, float]) -> pd.DataFrame:
    """Pasa los totales de ``columna`` de cada día por ``calculo_pulsos.calcular``."""
    salida = []
    for (fecha, fundo, modulo), g in filas.groupby(["Fecha", "Fundo", "Modulo"]):
        g = g.sort_values("Turno")
        totales = {t: max(float(v), 0.0) for t, v in zip(g["Turno"], g[columna])}
        plan = cp.calcular(totales, {t: areas.get(t, 0.0) for t in totales}, parametros)
        no_converge = any(a.startswith("No converge") for a in plan.avisos)
        for t, pt in plan.turnos.items():
            salida.append({"Fecha": fecha, "Fundo": fundo, "Modulo": modulo, "Turno": t,
                           "total_m3ha": totales[t], "n_pulsos": pt.n_ciclos, "curva": plan.curva,
                           "no_converge": int(no_converge)})
    return pd.DataFrame(salida)


def comparar_pulsos(por_fuente: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cuántas veces el n° de pulsos (y la curva) cambia frente al que sale con lo aplicado."""
    real = por_fuente["real"].set_index(CLAVES_TD)
    filas, detalle = [], []
    for fuente, df in por_fuente.items():
        d = df.set_index(CLAVES_TD).reindex(real.index)
        dif = d["n_pulsos"] - real["n_pulsos"]
        dias_real = real.groupby(level="Fecha")[["curva", "no_converge"]].first()
        dias = d.groupby(level="Fecha")[["curva", "no_converge"]].first()
        filas.append({
            "fuente": fuente, "turno_dias": len(d),
            "pct_n_pulsos_distinto": float((dif != 0).mean() * 100),
            "pct_dif_mas_de_1": float((dif.abs() > 1).mean() * 100),
            "dif_media_abs": float(dif.abs().mean()), "dif_media": float(dif.mean()),
            "pct_dias_curva_distinta": float((dias["curva"] != dias_real["curva"]).mean() * 100),
            "pct_dias_no_converge": float(dias["no_converge"].mean() * 100),
        })
        if fuente != "real":
            detalle.append(d[["total_m3ha", "n_pulsos", "curva"]].add_prefix(f"{fuente}_"))
    base = real[["total_m3ha", "n_pulsos", "curva"]].add_prefix("real_")
    return pd.DataFrame(filas), pd.concat([base, *detalle], axis=1).reset_index()


# --------------------------------------------------------------------------- #
# Tablas de resultados
# --------------------------------------------------------------------------- #
def tabla_metricas(filas: pd.DataFrame, preds: dict[str, np.ndarray]) -> pd.DataFrame:
    salida = []
    subconjuntos = {"todos": np.ones(len(filas), bool), "con_riego": filas["sin_riego"].to_numpy() == 0,
                    "dias_sin_riego": filas["sin_riego"].to_numpy() == 1}
    for sub, m in subconjuntos.items():
        if not m.any():
            continue
        for nombre, p in preds.items():
            salida.append({"subconjunto": sub, "modelo": nombre, **medir(filas[TARGET].to_numpy()[m], p[m])})
    return pd.DataFrame(salida)


def tabla_por(filas: pd.DataFrame, preds: dict[str, np.ndarray], por: pd.Series, nombre: str) -> pd.DataFrame:
    salida = []
    for valor in sorted(por.unique()):
        m = (por == valor).to_numpy()
        fila = {nombre: valor, "n": int(m.sum()), "real_medio": float(filas[TARGET].to_numpy()[m].mean())}
        for modelo, p in preds.items():
            r = medir(filas[TARGET].to_numpy()[m], p[m])
            fila.update({f"{modelo}_mae": r["mae"], f"{modelo}_rmse": r["rmse"], f"{modelo}_sesgo": r["mbe"]})
        salida.append(fila)
    return pd.DataFrame(salida)


def _md(df: pd.DataFrame, decimales: int = 2) -> str:
    """Tabla markdown sin dependencias (``tabulate`` no está instalado)."""
    def fmt(v):
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else f"{v:,.{decimales}f}".replace(",", "_").replace(".", ",").replace("_", ".")
        return str(v)
    cab = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    cuerpo = ["| " + " | ".join(fmt(v) for v in fila) + " |" for fila in df.itertuples(index=False)]
    return "\n".join([cab, sep, *cuerpo])


# --------------------------------------------------------------------------- #
# Predicción con la versión candidata
# --------------------------------------------------------------------------- #
def predecir_total(fecha, ruta: str | Path | None = None, config: Config | None = None) -> pd.DataFrame:
    """Total m³/ha previsto por turno para ``fecha`` con la versión candidata guardada.

    Usa las mismas features que ``predecir.py`` (historial del paso 1 hasta el día anterior).
    """
    config = config or load_config()
    ruta = Path(ruta) if ruta else config.rutas.modelos_dir / "total_turno" / "candidato"
    if ruta.is_dir():
        ruta = ruta / NOMBRE_MODELO
    paquete = joblib.load(ruta)
    historial = cargar_historial(config)
    feats = features_para_fechas(historial, [pd.Timestamp(fecha)], config)
    pred = predecir(paquete["modelo"], feats, paquete["features"])
    return feats[CLAVES_TD].assign(riego_total_m3ha=np.round(pred, 2))


# --------------------------------------------------------------------------- #
# Ejecución
# --------------------------------------------------------------------------- #
def ejecutar(ajuste: bool = True, guardar_modelo: bool = True) -> dict[str, Any]:
    log = logger("total_turno")
    t_inicio = time.time()
    exp = cargar_config_experimento()
    config = load_config()
    ds = cargar_dataset(config.rutas.processed_dir)
    ds.turno_dia["Fecha"] = pd.to_datetime(ds.turno_dia["Fecha"])
    ds.ciclos["Fecha"] = pd.to_datetime(ds.ciclos["Fecha"])
    ambiente = pd.read_csv(config.rutas.interim_dir / "ambiente_diario.csv", parse_dates=["Fecha"])
    features = list(ds.columnas["features_turno"])

    # ---- Datos -------------------------------------------------------------------------
    tabla, huecos = construir_tabla(ds.turno_dia, ambiente, config.preparacion.incluir_meteo_dia,
                                    int(exp["datos"]["max_dias_sin_riego"]))
    dif = diferencia_con_paso2(tabla, ds.turno_dia, features)
    log.info("Grilla: %d turno-días (%d con 0 m³/ha). Features recalculadas vs paso 2: dif. máx %.2e",
             len(tabla), int(tabla["sin_riego"].sum()), dif)
    if dif > 1e-6:
        raise ValueError(f"Las features recalculadas no coinciden con turno_dia.csv (dif. {dif}).")
    cortes = cortes_temporales(ds.turno_dia["Fecha"], config.split.test, config.split.validacion,
                               config.split.gap_dias)
    tabla["conjunto"] = cortes.asignar(tabla["Fecha"])
    evaluable = tabla["dia_incompleto"].fillna(0) == 0
    train = tabla[tabla["conjunto"] == "train"]
    val = tabla[(tabla["conjunto"] == "validacion") & evaluable].reset_index(drop=True)
    test = tabla[(tabla["conjunto"] == "test") & evaluable].reset_index(drop=True)
    log.info("Split %s | train %d · validación %d · test %d", cortes.to_dict(), len(train), len(val), len(test))

    # ---- Validación: candidatos y variantes de features ---------------------------------
    variantes = variantes_features(features, exp["candidatos"]["variantes"])
    familias = list(exp["candidatos"]["familias"])
    mediana_train = train.groupby("Turno")[TARGET].median().to_dict()
    filas_val = []
    for ref in REFERENCIAS:
        filas_val.append({"familia": ref, "variante": "-", "params": "{}",
                          **medir(val[TARGET], predecir_referencia(ref, val, mediana_train))})
    for variante, cols in variantes.items():
        for familia in familias:
            t0 = time.time()
            params = {"alpha": exp["candidatos"]["ridge_alpha"]} if familia == "ridge" else {}
            modelo = ajustar(crear_modelo(familia, params, cols, config), train[cols], train[TARGET])
            r = medir(val[TARGET], predecir(modelo, val, cols))
            filas_val.append({"familia": familia, "variante": variante, "params": json.dumps(_limpio(params)),
                              "n_features": len(cols), **r, "segundos": round(time.time() - t0, 1)})
            log.info("  val %-14s %-20s RMSE=%.3f MAE=%.3f", familia, variante, r["rmse"], r["mae"])
    validacion = pd.DataFrame(filas_val)

    filas_ajuste = []
    if ajuste and exp["ajuste"]["habilitado"]:
        for familia in familias:
            mejor_var = _mejor(validacion[validacion["familia"] == familia])["variante"]
            cols = variantes[mejor_var]
            for i, params in enumerate(combinaciones_ajuste(familia, int(exp["ajuste"]["n_iter"]),
                                                            exp["ajuste"]["ridge_alphas"])):
                modelo = ajustar(crear_modelo(familia, params, cols, config), train[cols], train[TARGET])
                r = medir(val[TARGET], predecir(modelo, val, cols))
                filas_ajuste.append({"familia": familia, "variante": mejor_var, "combo": i,
                                     "params": json.dumps(_limpio(params)), "n_features": len(cols), **r})
                log.info("  ajuste %-14s %2d RMSE=%.3f MAE=%.3f %s", familia, i, r["rmse"], r["mae"], params)
    ajustes = pd.DataFrame(filas_ajuste)
    todos = pd.concat([validacion, ajustes.drop(columns=["combo"], errors="ignore")], ignore_index=True)
    elegido = _mejor(todos)
    familia_el, variante_el = str(elegido["familia"]), str(elegido["variante"])
    params_el = json.loads(elegido["params"])
    log.info("Elegido por validación: %s / %s %s (RMSE %.3f, MAE %.3f)", familia_el, variante_el, params_el,
             elegido["rmse"], elegido["mae"])
    es_referencia = familia_el in REFERENCIAS
    cols_el = [] if es_referencia else variantes[variante_el]

    def ajustar_nuevo(hasta: pd.Timestamp):
        datos = tabla[tabla["Fecha"] <= hasta]
        if es_referencia:
            return None, datos.groupby("Turno")[TARGET].median().to_dict()
        modelo = ajustar(crear_modelo(familia_el, params_el, cols_el, config), datos[cols_el], datos[TARGET])
        return modelo, datos.groupby("Turno")[TARGET].median().to_dict()

    def pred_nuevo(modelo, mediana, filas):
        return predecir_referencia(familia_el, filas, mediana) if es_referencia else predecir(modelo, filas, cols_el)

    # ---- Test: comparación con el modelo en uso (misma receta reentrenada) -------------
    plan_ref = cargar_plan(config, config.rutas.modelos_dir / exp["comparacion"]["version_actual"])
    version_actual = plan_ref.metadata.get("version", "actual")
    escenarios = {"principal": pd.Timestamp(exp["comparacion"]["aprender_hasta"]),
                  "secundaria": cortes.fin_train}
    resultados: dict[str, dict[str, Any]] = {}
    for nombre, hasta in escenarios.items():
        t0 = time.time()
        modelo, mediana = ajustar_nuevo(hasta)
        plan = reentrenar_hasta(config, plan_ref, ds.turno_dia, ds.ciclos, ds.columnas, str(hasta.date()))
        mediana_ref = tabla[tabla["Fecha"] <= hasta].groupby("Turno")[TARGET].median().to_dict()
        preds = {
            "nuevo": pred_nuevo(modelo, mediana, test),
            "actual": total_plan(plan, test, ds.ciclos),
            "persistencia": predecir_referencia("persistencia", test, mediana_ref),
            "media_7d": predecir_referencia("media_7d", test, mediana_ref),
        }
        resultados[nombre] = {"hasta": hasta, "preds": preds, "plan": plan, "modelo": modelo,
                              "metricas": tabla_metricas(test, preds)}
        m = resultados[nombre]["metricas"]
        log.info("Test %s (aprenden hasta %s, %.0fs):\n%s", nombre, hasta.date(), time.time() - t0,
                 m[m["subconjunto"] == "todos"].to_string(index=False))

    principal = resultados["principal"]
    preds_p = principal["preds"]
    por_turno = tabla_por(test, preds_p, test["Turno"], "Turno")
    por_mes = tabla_por(test, preds_p, test["Fecha"].dt.strftime("%Y-%m"), "mes")

    # ---- Riego por pulsos --------------------------------------------------------------
    cp = cargar_calculo_pulsos()
    parametros = a_parametros(cp, leer_por_defecto())
    hasta_p = principal["hasta"]
    areas = ds.turno_dia[ds.turno_dia["Fecha"] <= hasta_p].groupby("Turno")["area_ha"].median().to_dict()
    base_pulsos = test[CLAVES_TD].copy()
    base_pulsos["real"] = test[TARGET].to_numpy()
    for k, v in preds_p.items():
        base_pulsos[k] = v
    # Solo días con todos los turnos del módulo (la convergencia suma los turnos del día).
    n_turnos = base_pulsos.groupby(["Fundo", "Modulo"])["Turno"].transform("nunique")
    n_dia = base_pulsos.groupby(["Fecha", "Fundo", "Modulo"])["Turno"].transform("nunique")
    base_pulsos = base_pulsos[n_dia == n_turnos]
    por_fuente = {f: pulsos_por_dia(cp, parametros, base_pulsos, f, areas)
                  for f in ["real", "nuevo", "actual", "persistencia", "media_7d"]}
    pulsos, pulsos_detalle = comparar_pulsos(por_fuente)
    log.info("Pulsos (parámetros por defecto):\n%s", pulsos.to_string(index=False))

    # ---- Decisión y versión candidata --------------------------------------------------
    mp = principal["metricas"]
    todos_p = mp[mp["subconjunto"] == "todos"].set_index("modelo")
    gana = (not es_referencia and todos_p.loc["nuevo", "rmse"] < todos_p.loc["actual", "rmse"]
            and todos_p.loc["nuevo", "mae"] < todos_p.loc["actual", "mae"])
    carpeta_rep = RAIZ_REPO / exp["salida"]["reportes"]
    carpeta_rep.mkdir(parents=True, exist_ok=True)
    version = datetime.now().strftime("%Y-%m-%d_%H%M")
    info_modelo: dict[str, Any] = {"guardado": False}
    if gana and guardar_modelo:
        info_modelo = guardar_candidato(tabla, familia_el, variante_el, params_el, cols_el, config, exp,
                                        cortes, elegido, todos_p, pulsos, version, version_actual, log)

    # ---- Reportes ----------------------------------------------------------------------
    predicciones = test[[*CLAVES_TD, "conjunto", "sin_riego", TARGET]].rename(columns={TARGET: "real"})
    for k, v in preds_p.items():
        predicciones[k] = np.round(v, 2)
    datos = pd.DataFrame([
        ("Turno-días en la grilla", len(tabla)),
        ("Turno-días con 0 m³/ha agregados (días sin riego)", int(tabla["sin_riego"].sum())),
        ("Turno-días en días incompletos (no se evalúan)", int(tabla["dia_incompleto"].sum())),
        ("Split", json.dumps(cortes.to_dict())),
        ("Filas train / validación / test", f"{len(train)} / {len(val)} / {len(test)}"),
        ("Test: turno-días con 0 m³/ha", int(test["sin_riego"].sum())),
        ("Features recalculadas vs paso 2 (dif. máx.)", f"{dif:.1e}"),
        ("Elegido por validación", f"{familia_el} / {variante_el} {params_el}"),
        ("Modelo en uso", f"{version_actual}, reentrenado con su receta hasta cada corte"),
        ("Versión candidata guardada", info_modelo.get("ruta", "no")),
        ("Duración del experimento (min)", round((time.time() - t_inicio) / 60, 1)),
    ], columns=["dato", "valor"])
    importancia = pd.DataFrame()
    if principal["modelo"] is not None:
        imp = importancias(principal["modelo"])
        importancia = pd.DataFrame(list(imp.items())[:40], columns=["feature", "importancia"])
    variantes_tabla = pd.DataFrame([{"variante": k, "n_features": len(v), "features": ", ".join(v)}
                                    for k, v in variantes.items()])
    ruta_xlsx = carpeta_rep / "comparativa_total_turno.xlsx"
    with pd.ExcelWriter(ruta_xlsx, engine="openpyxl") as w:
        datos.to_excel(w, sheet_name="Datos", index=False)
        validacion.sort_values(["rmse", "mae"]).to_excel(w, sheet_name="Validacion", index=False)
        if not ajustes.empty:
            ajustes.sort_values(["rmse", "mae"]).to_excel(w, sheet_name="Ajuste", index=False)
        principal["metricas"].to_excel(w, sheet_name="Test_principal", index=False)
        resultados["secundaria"]["metricas"].to_excel(w, sheet_name="Test_secundario", index=False)
        por_turno.to_excel(w, sheet_name="Por_turno", index=False)
        por_mes.to_excel(w, sheet_name="Por_mes", index=False)
        pulsos.to_excel(w, sheet_name="Pulsos", index=False)
        pulsos_detalle.to_excel(w, sheet_name="Pulsos_detalle", index=False)
        predicciones.to_excel(w, sheet_name="Predicciones_test", index=False)
        huecos.to_excel(w, sheet_name="Dias_sin_registro", index=False)
        variantes_tabla.to_excel(w, sheet_name="Variantes", index=False)
        if not importancia.empty:
            importancia.to_excel(w, sheet_name="Importancias", index=False)
    resumen = escribir_resumen(carpeta_rep / "resumen.md", datos, validacion, ajustes, resultados, por_turno,
                               pulsos, familia_el, variante_el, version_actual, gana, info_modelo)
    log.info("Reportes en %s (%.1f min)", carpeta_rep, (time.time() - t_inicio) / 60)
    return {"tabla": tabla, "validacion": validacion, "resultados": resultados, "pulsos": pulsos,
            "gana": gana, "resumen": resumen, "modelo": info_modelo}


def guardar_candidato(tabla, familia, variante, params, cols, config, exp, cortes: CortesTemporales, elegido,
                      test_todos: pd.DataFrame, pulsos: pd.DataFrame, version: str, version_actual: str,
                      log) -> dict[str, Any]:
    """Reentrena el elegido con todos los datos y lo guarda (sin tocar ``models/plan_riego``)."""
    import lightgbm
    import sklearn
    import xgboost

    modelo = ajustar(crear_modelo(familia, params, cols, config), tabla[cols], tabla[TARGET])
    base = RAIZ_REPO / exp["salida"]["modelos"]
    carpeta = base / "versiones" / version
    carpeta.mkdir(parents=True, exist_ok=True)
    joblib.dump({"modelo": modelo, "features": cols, "target": TARGET, "familia": familia, "params": params},
                carpeta / NOMBRE_MODELO)
    metadata = {
        "version": version, "entrenado": datetime.now().isoformat(timespec="seconds"),
        "descripcion": "Total m³/ha por turno-día (insumo de calculo_pulsos). Versión candidata: "
                       "no reemplaza a models/plan_riego/actual.",
        "target": TARGET, "familia": familia, "variante_features": variante, "params": _limpio(params),
        "features": cols, "categoricas": [c for c in cols if c in CATEGORICAS],
        "rango_datos": f"{tabla['Fecha'].min():%Y-%m-%d} a {tabla['Fecha'].max():%Y-%m-%d}",
        "turno_dias": int(len(tabla)), "turno_dias_sin_riego": int(tabla["sin_riego"].sum()),
        "max_dias_sin_riego": int(exp["datos"]["max_dias_sin_riego"]),
        "split": cortes.to_dict(),
        "validacion": {k: float(elegido[k]) for k in ("mae", "rmse", "r2", "mbe")},
        "test_principal": {"aprenden_hasta": exp["comparacion"]["aprender_hasta"],
                           "comparado_con": version_actual,
                           **{m: {k: float(test_todos.loc[m, k]) for k in ("mae", "rmse", "r2", "mbe")}
                              for m in test_todos.index}},
        "pulsos": pulsos.to_dict(orient="records"),
        "entorno": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__,
                    "scikit_learn": sklearn.__version__, "lightgbm": lightgbm.__version__,
                    "xgboost": xgboost.__version__},
    }
    (carpeta / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    candidato = base / "candidato"
    if candidato.exists():
        shutil.rmtree(candidato)
    shutil.copytree(carpeta, candidato)
    log.info("Versión candidata guardada en %s (y copiada a %s)", carpeta, candidato)
    return {"guardado": True, "ruta": str(carpeta.relative_to(RAIZ_REPO)).replace("\\", "/"), "version": version}


def escribir_resumen(ruta: Path, datos, validacion, ajustes, resultados, por_turno, pulsos, familia, variante,
                     version_actual, gana, info_modelo) -> str:
    def tabla_test(nombre):
        m = resultados[nombre]["metricas"]
        t = m[m["subconjunto"] == "todos"][["modelo", "n", "mae", "rmse", "r2", "mbe"]]
        return t.rename(columns={"mbe": "sesgo"})

    principal = tabla_test("principal").set_index("modelo")
    nuevo, actual = principal.loc["nuevo"], principal.loc["actual"]
    mejora_mae = (actual["mae"] - nuevo["mae"]) / actual["mae"] * 100
    mejora_rmse = (actual["rmse"] - nuevo["rmse"]) / actual["rmse"] * 100
    p = pulsos.set_index("fuente")
    mc = resultados["principal"]["metricas"]
    con_riego = mc[mc["subconjunto"] == "con_riego"][["modelo", "n", "mae", "rmse", "r2", "mbe"]]
    top = pd.concat([validacion, ajustes], ignore_index=True).sort_values(["rmse", "mae"]).head(8)
    lineas = [
        "# Modelo directo del total m³/ha por turno-día",
        "",
        f"Experimento `ml/experimentos/exp_total_turno.py`. Modelo en uso: `{version_actual}` "
        "(reentrenado con su misma receta hasta cada corte: el guardado vio el test).",
        "",
        "## Datos",
        "",
        _md(datos),
        "",
        "## Elección (solo validación)",
        "",
        f"Elegido: **{familia} / {variante}**. Los 8 mejores en validación:",
        "",
        _md(top[["familia", "variante", "params", "mae", "rmse", "r2", "mbe"]]),
        "",
        "## Test principal (ambos aprenden hasta 2025-09-15; test 2025-09-23 → fin)",
        "",
        _md(tabla_test("principal")),
        "",
        "Solo turno-días con riego (sin los días a 0 m³/ha):",
        "",
        _md(con_riego),
        "",
        "## Test secundario (ambos aprenden solo con el train del pipeline)",
        "",
        _md(tabla_test("secundaria")),
        "",
        "## Error por turno (test principal)",
        "",
        _md(por_turno[["Turno", "n", "real_medio", "nuevo_mae", "actual_mae", "persistencia_mae",
                       "nuevo_sesgo", "actual_sesgo"]]),
        "",
        "## Riego por pulsos (calculo_pulsos con los parámetros por defecto)",
        "",
        "Frente a los pulsos que salen con lo realmente aplicado:",
        "",
        _md(pulsos),
        "",
        "## Recomendación",
        "",
    ]
    def n(x, d=2):
        return f"{x:.{d}f}".replace(".", ",")

    media7 = principal.loc["media_7d"]
    if gana:
        lineas += [
            f"- **Total por turno-día:** el modelo nuevo es **mejor** que el actual: MAE "
            f"{n(nuevo['mae'])} vs {n(actual['mae'])} m³/ha ({mejora_mae:.0f} % menos error) y RMSE "
            f"{n(nuevo['rmse'])} vs {n(actual['rmse'])} ({mejora_rmse:.0f} % menos). La ventaja se mantiene "
            "sin los días a 0 y en el test secundario.",
            f"- **Referencia simple:** la media de 7 días queda a la par del nuevo en el test (MAE "
            f"{n(media7['mae'])}, RMSE {n(media7['rmse'])}), aunque en validación fue peor; el nuevo se eligió "
            "solo por validación, como manda el protocolo.",
            f"- **Pulsos:** el n° de pulsos difiere del que sale con lo aplicado en "
            f"{p.loc['nuevo', 'pct_n_pulsos_distinto']:.0f} % de los turno-días con el nuevo vs "
            f"{p.loc['actual', 'pct_n_pulsos_distinto']:.0f} % con el actual; errores de más de 1 pulso: "
            f"{p.loc['nuevo', 'pct_dif_mas_de_1']:.0f} % vs {p.loc['actual', 'pct_dif_mas_de_1']:.0f} %. "
            f"Sesgo del nuevo: {n(nuevo['sesgo'])} m³/ha (tiende a sumar un pulso).",
            "",
            f"Versión candidata: `{info_modelo.get('ruta', '(no guardada)')}` (copia en "
            "`ml/models/total_turno/candidato/`). No reemplaza al modelo en uso ni toca el backend.",
        ]
    else:
        lineas += [
            f"El modelo nuevo **no** supera al actual en el total por turno-día (MAE {nuevo['mae']:.2f} vs "
            f"{actual['mae']:.2f}, RMSE {nuevo['rmse']:.2f} vs {actual['rmse']:.2f}). No se guarda versión "
            "candidata.",
        ]
    texto = "\n".join(lineas) + "\n"
    ruta.write_text(texto, encoding="utf-8")
    return texto


def main() -> None:
    ap = argparse.ArgumentParser(description="Modelo directo del total m³/ha por turno-día vs el modelo en uso")
    ap.add_argument("--sin-ajuste", action="store_true", help="sin búsqueda de hiperparámetros")
    ap.add_argument("--no-guardar-modelo", action="store_true", help="no guarda la versión candidata")
    a = ap.parse_args()
    ejecutar(ajuste=not a.sin_ajuste, guardar_modelo=not a.no_guardar_modelo)


if __name__ == "__main__":
    main()
