"""Experimento: reducir los "muchos ciclos" del cronograma por pulsos.

Con riego por pulsos solo se usa el total de m³/ha de cada turno-día: ``calculo_pulsos`` arma
los pulsos (n ≈ round(total / volumen del pulso)). Si el total sale alto, salen pulsos de más.
Este experimento compara formas de predecir ese total, con datos hasta el 20/11/2026:

* Referencias: ayer, media 3 días, media 7 días, mediana 7 días.
* Modelo en uso (plan_riego/portable): suma de los m³/ha de sus ciclos (n_ciclos × m³/ciclo).
* Candidato total_turno (rama feature/modelo-total-turno, congelado al 04/11).
* Modelos directos del total (RF, LightGBM, HistGB), con y sin pesos por antigüedad.
* Modelos residuales: total = nivel reciente (media 7 d / ayer / media 3 d) + ajuste aprendido.

Protocolo (sin fugas): las features de un día solo usan días anteriores (``construir_features_turno``).
Cada candidato se reentrena en cada "origen" con los días < origen y predice los días siguientes
hasta el próximo origen (un paso adelante, con el riego real hasta el día anterior). Los días
incompletos (faltan turnos) no se evalúan.

No toca ``ml/src``, ``config/pipeline.yaml`` ni ``models/``. Salida: ``reports/experimentos/reducir_ciclos``.

Uso (desde ml/): .venv/Scripts/python experimentos/exp_reducir_ciclos.py
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

RAIZ_ML = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ_ML / "src"))
for _f in (sys.stdout, sys.stderr):
    if hasattr(_f, "reconfigure"):
        _f.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

from lightgbm import LGBMRegressor  # noqa: E402
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor  # noqa: E402

from riego_ml.dataset.features import columnas_features, construir_features_turno  # noqa: E402
from riego_ml.dataset.limpieza import CLAVES_TD, limpiar_ciclos, tabla_turno_dia  # noqa: E402
from riego_ml.sources.riego import COLUMNAS_RIEGO  # noqa: E402
from riego_ml.utils.tiempo import minutes_to_hhmm  # noqa: E402

DATOS = RAIZ_ML / "data" / "exp_ciclos"
SALIDA = RAIZ_ML / "reports" / "experimentos" / "reducir_ciclos"
PULSO = 9.8            # m³/ha por pulso en producción (AD 166,67 × δ 5 % / Ea 0,85)
CORTE_AMBIENTE = pd.Timestamp("2026-11-01")
ULTIMO_DIA = pd.Timestamp("2026-11-20")
SEED = 42

CALENDARIO = {"mes", "dia_semana", "doy_sin", "doy_cos", "turno_num", "es_feriado", "vispera_feriado", "post_feriado"}
PREF_CLIMA = ("T_", "HR_", "ETo_", "DPV_", "Viento_", "Lluvia_", "Rad_", "horas_T30")
PREF_SUELO = ("d_hum_", "resp_hum_", "hum_", "dist_linea")
PREF_PLANTA = ("mds_", "crecimiento_", "estres_", "ndvi_")


# --------------------------------------------------------------------------- datos
def ajustar_medianoche(ciclos: pd.DataFrame, max_hora: float = 120.0, max_brecha: float = 180.0, factor: float = 3.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Un ciclo que empieza pasada la medianoche (antes de ``max_hora``) pasa al día anterior si
    sigue de cerca al último ciclo de ese turno (≤ ``max_brecha`` min) y el siguiente ciclo del
    mismo día está al menos ``factor`` veces más lejos. Caso típico: TE05 00:05 del 17/11."""
    c = ciclos.copy()
    c["_ini"] = c["Fecha"] + pd.to_timedelta(c["inicio_min"], unit="min")
    c["_fin"] = c["Fecha"] + pd.to_timedelta(c["fin_min"], unit="min")
    c = c.sort_values(["Turno", "_ini"]).reset_index(drop=True)
    movidos = []
    for _, g in c.groupby("Turno"):
        idx = list(g.index)
        for k, i in enumerate(idx):
            if c.at[i, "inicio_min"] >= max_hora or k == 0:
                continue
            previo = idx[k - 1]
            if c.at[previo, "Fecha"] != c.at[i, "Fecha"] - pd.Timedelta(days=1):
                continue
            brecha_prev = (c.at[i, "_ini"] - c.at[previo, "_fin"]).total_seconds() / 60
            sig = idx[k + 1] if k + 1 < len(idx) and c.at[idx[k + 1], "Fecha"] == c.at[i, "Fecha"] else None
            brecha_sig = (c.at[sig, "_ini"] - c.at[i, "_fin"]).total_seconds() / 60 if sig is not None else np.inf
            if 0 <= brecha_prev <= max_brecha and brecha_sig >= factor * brecha_prev:
                movidos.append({"Turno": c.at[i, "Turno"], "de": c.at[i, "Fecha"].date(),
                                "hora": c.at[i, "hora_inicio"], "brecha_previa_min": round(brecha_prev),
                                "brecha_siguiente_min": None if np.isinf(brecha_sig) else round(brecha_sig)})
                c.at[i, "Fecha"] -= pd.Timedelta(days=1)
                c.at[i, "inicio_min"] += 1440
                c.at[i, "fin_min"] += 1440
                c.at[i, "fin_dia_siguiente"] = 1
    return c.drop(columns=["_ini", "_fin"]), pd.DataFrame(movidos)


def cargar_datos() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    hist = pd.read_csv(RAIZ_ML / "data/interim/riego_unido.csv", parse_dates=["Fecha"])[COLUMNAS_RIEGO]
    fundo, modulo = hist["Fundo"].iloc[0], hist["Modulo"].iloc[0]
    fab = pd.read_csv(DATOS / "riego_fabric.csv", parse_dates=["fecha"])
    nuevo = pd.DataFrame({
        "Fecha": fab["fecha"], "Fundo": fundo, "Modulo": modulo, "Turno": fab["turno"],
        "Valvula": pd.to_numeric(fab["valvula"], errors="coerce").fillna(0).astype("int64"),
        "inicio_min": fab["inicio_min"], "fin_min": fab["fin_min"],
        "hora_inicio": fab["inicio_min"].map(minutes_to_hhmm), "hora_fin": fab["fin_min"].map(minutes_to_hhmm),
        "fin_dia_siguiente": (fab["fin_min"] >= 1440).astype(int), "duracion_min": fab["duracion_min"],
        "riego_m3": fab["riego_m3"], "riego_m3ha": fab["riego_m3ha"], "area_ha": fab["area_ha"],
    })
    riego = pd.concat([hist[hist["Fecha"] < nuevo["Fecha"].min()], nuevo], ignore_index=True)
    riego, movidos = ajustar_medianoche(riego)
    ciclos, _, _ = limpiar_ciclos(riego, 5.0, 2.0)

    archivo = pd.read_csv(RAIZ_ML / "data/interim/ambiente_diario.csv", parse_dates=["Fecha"])
    bd = pd.read_csv(DATOS / "ambiente_riego_dev.csv", parse_dates=["Fecha"])
    bd["Fundo"] = archivo["Fundo"].iloc[0]
    ambiente = pd.concat([archivo[archivo["Fecha"] <= CORTE_AMBIENTE],
                          bd[bd["Fecha"] > CORTE_AMBIENTE][archivo.columns]], ignore_index=True)
    return ciclos, tabla_turno_dia(ciclos), ambiente.sort_values("Fecha").reset_index(drop=True), movidos


def referencias(td: pd.DataFrame, fechas_extra: list[pd.Timestamp] = ()) -> pd.DataFrame:
    """Ayer / media 3 / media 7 / mediana 7 del total del mismo turno, solo días anteriores."""
    salida = []
    for (fundo, modulo, turno), g in td.groupby(["Fundo", "Modulo", "Turno"]):
        s = g.set_index("Fecha")["riego_total_m3ha"]
        idx = pd.date_range(s.index.min(), max([s.index.max(), *fechas_extra]), freq="D")
        p = s.reindex(idx).shift(1)
        salida.append(pd.DataFrame({
            "Fecha": idx, "Fundo": fundo, "Modulo": modulo, "Turno": turno, "ref_ayer": p.to_numpy(),
            "ref_media3": p.rolling(3, min_periods=2).mean().to_numpy(),
            "ref_media7": p.rolling(7, min_periods=3).mean().to_numpy(),
            "ref_mediana7": p.rolling(7, min_periods=3).median().to_numpy()}))
    return pd.concat(salida, ignore_index=True)


def construir_tabla(td: pd.DataFrame, ambiente: pd.DataFrame, claves: pd.DataFrame | None = None) -> pd.DataFrame:
    claves = td[CLAVES_TD] if claves is None else claves
    feats = construir_features_turno(claves, td, ambiente, False)
    tabla = claves.merge(td[[*CLAVES_TD, "riego_total_m3ha", "n_ciclos", "dia_incompleto"]], on=CLAVES_TD, how="left")
    tabla = tabla.merge(feats, on=CLAVES_TD, how="left")
    extra = sorted(set(claves["Fecha"]) - set(td["Fecha"]))
    return tabla.merge(referencias(td, extra), on=CLAVES_TD, how="left")


def grupos(features: list[str]) -> dict[str, list[str]]:
    g = {"calendario": [], "riego": [], "clima": [], "suelo": [], "planta": []}
    for c in features:
        if c in CALENDARIO:
            g["calendario"].append(c)
        elif c.startswith(PREF_SUELO):
            g["suelo"].append(c)
        elif c.startswith(PREF_PLANTA):
            g["planta"].append(c)
        elif c.startswith(PREF_CLIMA) or c in ("balance_hidrico_7d", "reposicion_7d"):
            g["clima"].append(c)
        else:
            g["riego"].append(c)
    return g


# --------------------------------------------------------------------------- candidatos
def estimador(familia: str):
    if familia == "rf":
        return RandomForestRegressor(n_estimators=300, max_depth=12, min_samples_leaf=5, max_features="sqrt",
                                     n_jobs=-1, random_state=SEED)
    if familia == "lgbm":
        return LGBMRegressor(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=20,
                             subsample=0.9, subsample_freq=1, colsample_bytree=0.8, random_state=SEED, verbose=-1)
    if familia == "hgb":
        return HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                                             min_samples_leaf=20, random_state=SEED)
    raise ValueError(familia)


class Candidato:
    def __init__(self, nombre, familia, columnas, base=None, vida_media=None):
        self.nombre, self.familia, self.columnas = nombre, familia, columnas
        self.base, self.vida_media = base, vida_media  # base: columna ref_* (residual) o None (directo)

    def _y(self, t):
        return t["riego_total_m3ha"] - t[self.base] if self.base else t["riego_total_m3ha"]

    def ajustar(self, train: pd.DataFrame):
        t = train.dropna(subset=["riego_total_m3ha", *([self.base] if self.base else [])])
        X = t[self.columnas].astype(float)
        if self.familia == "rf":
            X = X.fillna(-999)
        w = None
        if self.vida_media:
            edad = (t["Fecha"].max() - t["Fecha"]).dt.days.to_numpy()
            w = 0.5 ** (edad / self.vida_media)
        self.m = estimador(self.familia).fit(X, self._y(t), sample_weight=w)
        return self

    def predecir(self, filas: pd.DataFrame) -> np.ndarray:
        X = filas[self.columnas].astype(float)
        if self.familia == "rf":
            X = X.fillna(-999)
        p = self.m.predict(X)
        if self.base:
            base = filas[self.base].fillna(filas["ref_media7"]).fillna(filas["ref_ayer"]).to_numpy()
            p = base + p
        return np.clip(p, 0, None)


def candidatos(features: list[str]) -> list[Candidato]:
    g = grupos(features)
    riego = g["calendario"] + g["riego"]
    riego_clima = riego + g["clima"]
    completo = riego_clima + g["suelo"] + g["planta"]
    refs = ["ref_ayer", "ref_media3", "ref_media7", "ref_mediana7"]
    return [
        Candidato("directo_rf_riego", "rf", riego),                          # receta del candidato previo
        Candidato("directo_rf_riego_clima", "rf", riego_clima + refs),
        Candidato("directo_lgbm_riego_clima", "lgbm", riego_clima + refs),
        Candidato("directo_lgbm_completo", "lgbm", completo + refs),
        Candidato("directo_lgbm_peso90", "lgbm", riego_clima + refs, vida_media=90),
        Candidato("directo_lgbm_peso30", "lgbm", riego_clima + refs, vida_media=30),
        Candidato("resid7_lgbm_riego_clima", "lgbm", riego_clima + refs, base="ref_media7"),
        Candidato("resid7_hgb_riego_clima", "hgb", riego_clima + refs, base="ref_media7"),
        Candidato("resid7_rf_riego_clima", "rf", riego_clima + refs, base="ref_media7"),
        Candidato("resid3_lgbm_riego_clima", "lgbm", riego_clima + refs, base="ref_media3"),
        Candidato("residayer_lgbm_riego_clima", "lgbm", riego_clima + refs, base="ref_ayer"),
        Candidato("resid7_lgbm_peso90", "lgbm", riego_clima + refs, base="ref_media7", vida_media=90),
    ]


# --------------------------------------------------------------------------- evaluación
def walk_forward(tabla: pd.DataFrame, cands: list[Candidato], desde: str, hasta: str, paso_dias: int) -> pd.DataFrame:
    filas = []
    origenes = pd.date_range(desde, hasta, freq=f"{paso_dias}D")
    for k, origen in enumerate(origenes):
        fin = origenes[k + 1] if k + 1 < len(origenes) else pd.Timestamp(hasta) + pd.Timedelta(days=1)
        train = tabla[(tabla["Fecha"] < origen) & (tabla["dia_incompleto"] == 0)]
        test = tabla[(tabla["Fecha"] >= origen) & (tabla["Fecha"] < fin)]
        if test.empty:
            continue
        out = test[[*CLAVES_TD, "riego_total_m3ha", "n_ciclos", "dia_incompleto",
                    "ref_ayer", "ref_media3", "ref_media7", "ref_mediana7"]].copy()
        for c in cands:
            out[c.nombre] = c.ajustar(train).predecir(test)
        filas.append(out)
    return pd.concat(filas, ignore_index=True)


def pulsos(x) -> np.ndarray:
    return np.maximum(1, np.floor(np.asarray(x, dtype=float) / PULSO + 0.5)).astype(int)


def metricas(df: pd.DataFrame, columnas: list[str]) -> pd.DataFrame:
    d = df[(df["dia_incompleto"] == 0) & df["riego_total_m3ha"].notna() & (df["riego_total_m3ha"] > 0)]
    real = d["riego_total_m3ha"].to_numpy()
    pr = pulsos(real)
    salida = {}
    for c in columnas:
        p = d[c].to_numpy(dtype=float)
        ok = ~np.isnan(p)
        e = p[ok] - real[ok]
        dp = pulsos(p[ok]) - pr[ok]
        salida[c] = {"n": int(ok.sum()), "MAE_m3ha": np.abs(e).mean(), "sesgo_m3ha": e.mean(),
                     "error_%": (e / real[ok]).mean() * 100,
                     "pulsos_iguales_%": (dp == 0).mean() * 100, "pulsos_±1_%": (np.abs(dp) <= 1).mean() * 100,
                     "pulsos_de_más_2+_%": (dp >= 2).mean() * 100, "pulsos_sesgo": dp.mean()}
    return pd.DataFrame(salida).T.sort_values("MAE_m3ha")


# --------------------------------------------------------------------------- modelos guardados
def total_plan_actual(tabla: pd.DataFrame, ciclos: pd.DataFrame, fechas) -> pd.DataFrame:
    """Modelo en uso: suma de los m³/ha de los ciclos que predice, con el riego real hasta D-1."""
    plan = joblib.load(RAIZ_ML / "models/plan_riego/portable/modelo_plan_riego.joblib")
    filas = []
    for dia in fechas:
        f = tabla[tabla["Fecha"] == dia]
        if f.empty:
            continue
        p = plan.predecir(f, ciclos[ciclos["Fecha"] < dia])
        filas.append(p.groupby(CLAVES_TD, as_index=False)["riego_m3ha"].sum().rename(columns={"riego_m3ha": "actual_plan"}))
    return pd.concat(filas, ignore_index=True)


def total_candidato_previo(tabla: pd.DataFrame) -> np.ndarray:
    o = joblib.load(RAIZ_ML / "models/total_turno/candidato/modelo_total_turno.joblib")
    return o["modelo"].predict(tabla[o["features"]])


# --------------------------------------------------------------------------- main
def main() -> None:
    t0 = time.time()
    SALIDA.mkdir(parents=True, exist_ok=True)
    ciclos, td, ambiente, movidos = cargar_datos()
    print(f"Ciclos {len(ciclos)} · turno-días {len(td)} · {td.Fecha.min():%Y-%m-%d} a {td.Fecha.max():%Y-%m-%d}")
    print("Ciclos movidos al día anterior (regla de medianoche):", len(movidos))
    tabla = construir_tabla(td, ambiente)
    fuera = {"Turno", "riego_total_m3ha", "n_ciclos", "dia_incompleto", "ref_ayer", "ref_media3", "ref_media7", "ref_mediana7"}
    features = [c for c in columnas_features(tabla, False, True) if c not in fuera]
    cands = candidatos(features)
    refs = ["ref_ayer", "ref_media3", "ref_media7", "ref_mediana7"]
    nombres = [c.nombre for c in cands]

    # 1) Régimen nuevo (05–20/11): reentreno diario y semanal. 2) Antes del cambio (oct). 3) Largo plazo.
    resultados = {}
    nov_d = walk_forward(tabla, cands, "2026-11-05", "2026-11-20", 1)
    nov_s = walk_forward(tabla, cands, "2026-11-05", "2026-11-20", 7)
    oct_s = walk_forward(tabla, cands, "2026-10-01", "2026-11-04", 7)
    largo = walk_forward(tabla, cands, "2025-09-23", "2026-11-20", 28)
    fechas_nov = pd.date_range("2026-11-05", "2026-11-20")
    act = total_plan_actual(tabla, ciclos, list(fechas_nov) + list(pd.date_range("2026-10-01", "2026-11-04")))
    previo = tabla[[*CLAVES_TD]].assign(candidato_previo_0411=total_candidato_previo(tabla))
    for nombre, df in (("nov_diario", nov_d), ("nov_semanal", nov_s), ("oct_semanal", oct_s), ("largo_28d", largo)):
        df = df.merge(act, on=CLAVES_TD, how="left").merge(previo, on=CLAVES_TD, how="left")
        df.to_csv(SALIDA / f"predicciones_{nombre}.csv", index=False)
        cols = refs + nombres + ["candidato_previo_0411"] + (["actual_plan"] if df["actual_plan"].notna().any() else [])
        resultados[nombre] = metricas(df, cols)
        if nombre.startswith("nov"):
            resultados[nombre + "_14a20"] = metricas(df[df.Fecha >= "2026-11-14"], cols)
            resultados[nombre + "_19"] = metricas(df[df.Fecha == "2026-11-19"], cols)
    with pd.ExcelWriter(SALIDA / "metricas.xlsx") as xl:
        for k, v in resultados.items():
            v.round(2).to_excel(xl, sheet_name=k[:31])
        movidos.to_excel(xl, sheet_name="medianoche", index=False)
    for k, v in resultados.items():
        print(f"\n=== {k} ===\n", v.round(2).to_string())
    (SALIDA / "features.json").write_text(json.dumps(grupos(features), indent=1), encoding="utf-8")
    print(f"\nListo en {(time.time() - t0) / 60:.1f} min · {SALIDA}")


if __name__ == "__main__":
    main()
