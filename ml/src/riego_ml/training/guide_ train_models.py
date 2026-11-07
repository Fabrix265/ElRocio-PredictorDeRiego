#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
train_models.py
===============
Compara MLP, Random Forest, SVR y XGBoost para predecir el plan de riego:

    n_ciclos      (turno_dia.csv)   -> por turno y dia
    riego_m3ha    (ciclos.csv)      -> por ciclo
    duracion_min  (ciclos.csv)      -> por ciclo
    inicio_min    (ciclos.csv)      -> por ciclo (minutos desde 00:00)
    fin_min       = inicio_min + duracion_min   (derivado, tambien se evalua)

Protocolo
---------
- Split TEMPORAL: se entrena con el pasado y se prueba con el futuro (gap de 3 dias).
- Hiperparametros: RandomizedSearchCV con TimeSeriesSplit dentro del train.
- Imputacion (mediana + indicador de nulo) y escalado dentro de cada pipeline
  (se ajustan solo con train, sin fuga).
- Referencia: "Persistencia" (lo que hizo el mismo turno/ciclo el dia anterior).
  Si un modelo no la supera, no aporta valor.

Metricas: RMSE, MAE, R2, MBE (sesgo), r (Pearson), KGE, NSE, d de Willmott,
          NRMSE %, MAPE %, rho (Spearman) y, para n_ciclos, acierto exacto y +-1.

Salidas (en --modelo-dir)
-------------------------
    metricas_test.csv / metricas_cv.csv / metricas.xlsx
    predicciones_test_<target>.csv
    modelo_<target>.joblib     (mejor modelo por RMSE en validacion cruzada)
    modelo_riego.joblib        (paquete con los 4 mejores + datos para predecir_plan)

Uso
---
    python train_models.py --datos-dir ml/data/processed
    python train_models.py --rapido                      # prueba veloz
    python train_models.py --desde 2023-10-01            # solo periodo con suelo completo
"""

from __future__ import annotations

import argparse
import json
import time
import warnings
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr
from sklearn.base import clone
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.model_selection import RandomizedSearchCV, TimeSeriesSplit
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR
from xgboost import XGBRegressor

warnings.filterwarnings("ignore")

ML_ROOT = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) > 3 else Path.cwd()
GAP_DIAS = 3
PAUSA_MIN = 10
SEED = 42

# (nombre de salida, tabla, columna prev para la persistencia)
TARGETS = {
    "n_ciclos": ("turno_dia", "prev_n_ciclos"),
    "riego_m3ha": ("ciclos", "prev_m3ha_ciclo"),
    "duracion_min": ("ciclos", "prev_dur_ciclo"),
    "inicio_min": ("ciclos", "prev_inicio_ciclo"),
}


# --------------------------------------------------------------------------- #
# Metricas
# --------------------------------------------------------------------------- #
def metricas(obs, sim, redondeado: bool = False) -> dict:
    o, s = np.asarray(obs, float), np.asarray(sim, float)
    m = ~(np.isnan(o) | np.isnan(s))
    o, s = o[m], s[m]
    err = s - o
    rmse = float(np.sqrt(np.mean(err**2)))
    mae = float(np.mean(np.abs(err)))
    mbe = float(np.mean(err))
    ss_res, ss_tot = np.sum(err**2), np.sum((o - o.mean()) ** 2)
    r2 = float(1 - ss_res / ss_tot)                       # = NSE
    r = float(pearsonr(o, s)[0]) if np.std(s) > 0 and np.std(o) > 0 else np.nan
    rho = float(spearmanr(o, s)[0]) if np.std(s) > 0 and np.std(o) > 0 else np.nan
    alpha = s.std() / o.std() if o.std() > 0 else np.nan  # variabilidad relativa
    beta = s.mean() / o.mean() if o.mean() != 0 else np.nan  # sesgo relativo
    kge = float(1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)) if not np.isnan(r) else np.nan
    willmott = float(1 - ss_res / np.sum((np.abs(s - o.mean()) + np.abs(o - o.mean())) ** 2))
    pos = o > 1e-6
    mape = float(np.mean(np.abs(err[pos] / o[pos])) * 100) if pos.any() else np.nan
    out = {
        "RMSE": rmse, "MAE": mae, "R2": r2, "MBE": mbe, "r": r, "KGE": kge,
        "NSE": r2, "Willmott_d": willmott, "NRMSE_%": rmse / o.mean() * 100 if o.mean() else np.nan,
        "MAPE_%": mape, "Spearman_rho": rho, "KGE_alpha": float(alpha), "KGE_beta": float(beta),
        "n": int(len(o)),
    }
    if redondeado:  # solo n_ciclos (conteo entero)
        sr = np.rint(s)
        out["Acierto_exacto"] = float((sr == o).mean())
        out["Acierto_+-1"] = float((np.abs(sr - o) <= 1).mean())
    return out


# --------------------------------------------------------------------------- #
# Modelos y espacios de busqueda
# --------------------------------------------------------------------------- #
def _prep(scale: bool) -> list:
    steps = [("imp", SimpleImputer(strategy="median", add_indicator=True))]
    if scale:
        steps.append(("sc", StandardScaler()))
    return steps


def modelos(n_jobs: int) -> dict:
    """nombre -> (estimador, espacio de busqueda)"""
    rf = Pipeline(_prep(False) + [("m", RandomForestRegressor(random_state=SEED, n_jobs=n_jobs))])
    xgb = Pipeline(_prep(False) + [("m", XGBRegressor(random_state=SEED, n_jobs=n_jobs, tree_method="hist"))])
    svr = TransformedTargetRegressor(
        Pipeline(_prep(True) + [("m", SVR(kernel="rbf"))]), transformer=StandardScaler())
    mlp = TransformedTargetRegressor(
        Pipeline(_prep(True) + [("m", MLPRegressor(max_iter=400, early_stopping=True,
                                                   n_iter_no_change=15, random_state=SEED))]),
        transformer=StandardScaler())
    p = lambda s: "regressor__m__" + s  # noqa: E731
    return {
        "RandomForest": (rf, {
            "m__n_estimators": [200, 400], "m__max_depth": [6, 10, None],
            "m__min_samples_leaf": [5, 20, 50], "m__max_features": [0.3, 0.6, 1.0]}),
        "XGBoost": (xgb, {
            "m__n_estimators": [200, 400], "m__max_depth": [3, 5], "m__learning_rate": [0.03, 0.08],
            "m__subsample": [0.7, 1.0], "m__colsample_bytree": [0.6, 1.0], "m__min_child_weight": [5, 20]}),
        "SVR": (svr, {
            p("C"): [1, 10, 100], p("epsilon"): [0.05, 0.1, 0.2], p("gamma"): ["scale", 0.01, 0.001]}),
        "MLP": (mlp, {
            p("hidden_layer_sizes"): [(64,), (64, 32), (128, 64)], p("alpha"): [1e-4, 1e-3, 1e-2],
            p("learning_rate_init"): [1e-3, 3e-3]}),
    }


# --------------------------------------------------------------------------- #
# Persistencia (referencia)
# --------------------------------------------------------------------------- #
def persistencia(df_tr: pd.DataFrame, df_te: pd.DataFrame, target: str, prev: str, keys: list[str]) -> np.ndarray:
    tab = df_tr.groupby(keys)[target].median()
    idx = pd.MultiIndex.from_frame(df_te[keys]) if len(keys) > 1 else pd.Index(df_te[keys[0]])
    fb = tab.reindex(idx).to_numpy(float)
    fb = np.where(np.isnan(fb), df_tr[target].median(), fb)
    return np.where(df_te[prev].notna(), df_te[prev].to_numpy(float), fb)


# --------------------------------------------------------------------------- #
# Plan de riego con los mejores modelos
# --------------------------------------------------------------------------- #
def fmt_hhmm(minutes: float) -> str:
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def predecir_plan(bundle: dict, X: pd.DataFrame, hist_ciclos: pd.DataFrame | None = None) -> pd.DataFrame:
    """X: filas turno-dia con 'Fecha','Turno' + features_turno_dia.
    hist_ciclos: ciclos reales (ciclos.csv) para los lags del dia anterior (opcional)."""
    X = X.reset_index(drop=True)
    n_pred = np.clip(np.rint(bundle["modelos"]["n_ciclos"].predict(X[bundle["features_turno_dia"]])),
                     1, bundle["max_ciclos"]).astype(int)
    rep = X.loc[X.index.repeat(n_pred)].copy()
    rep["n_ciclos"] = np.repeat(n_pred, n_pred)
    rep["Ciclo"] = np.concatenate([np.arange(1, n + 1) for n in n_pred])

    prev_cols = ["prev_m3ha_ciclo", "prev_inicio_ciclo", "prev_dur_ciclo", "prev_fin_ciclo"]
    rep = rep.drop(columns=[c for c in prev_cols if c in rep.columns])
    if hist_ciclos is not None:
        pc = hist_ciclos[["Fecha", "Turno", "Ciclo", "riego_m3ha", "inicio_min", "duracion_min", "fin_min"]].copy()
        pc["Fecha"] += pd.Timedelta(days=1)
        pc = pc.rename(columns=dict(zip(["riego_m3ha", "inicio_min", "duracion_min", "fin_min"], prev_cols)))
        rep = rep.merge(pc, on=["Fecha", "Turno", "Ciclo"], how="left")
    else:
        for c in prev_cols:
            rep[c] = np.nan
    rep = rep.reset_index(drop=True)

    F = bundle["features_ciclo"]
    for t in ("riego_m3ha", "duracion_min", "inicio_min"):
        rep[t] = bundle["modelos"][t].predict(rep[F])
    rep["riego_m3ha"] = rep["riego_m3ha"].clip(*bundle["rango"]["riego_m3ha"])
    rep["duracion_min"] = rep["duracion_min"].clip(*bundle["rango"]["duracion_min"])
    rep["inicio_min"] = rep["inicio_min"].clip(0, 1439)

    rep = rep.sort_values(["Fecha", "Turno", "inicio_min"]).reset_index(drop=True)
    rep["Ciclo"] = rep.groupby(["Fecha", "Turno"]).cumcount() + 1
    ini, fin = [], []
    for _, g in rep.groupby(["Fecha", "Turno"], sort=False):
        pf = -np.inf
        for i, d in zip(g["inicio_min"], g["duracion_min"]):
            i = max(i, pf + PAUSA_MIN)
            pf = i + d
            ini.append(i)
            fin.append(pf)
    rep["inicio_min"], rep["fin_min"] = ini, fin
    rep["hora_inicio"] = rep["inicio_min"].map(fmt_hhmm)
    rep["hora_fin"] = rep["fin_min"].map(fmt_hhmm)
    rep["fin_dia_siguiente"] = (rep["fin_min"] >= 1440).astype(int)
    return rep[["Fecha", "Turno", "n_ciclos", "Ciclo", "riego_m3ha", "duracion_min",
                "hora_inicio", "hora_fin", "fin_dia_siguiente"]].round({"riego_m3ha": 2, "duracion_min": 1})


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Comparativa MLP / RF / SVR / XGBoost para el plan de riego.")
    ap.add_argument("--datos-dir", type=Path, default=ML_ROOT / "data" / "processed")
    ap.add_argument("--modelo-dir", type=Path, default=ML_ROOT / "models")
    ap.add_argument("--corte", type=str, default=None, help="YYYY-MM-DD: desde ahi es test (def. ultimo 20%% de fechas).")
    ap.add_argument("--desde", type=str, default=None, help="Usar solo datos desde esta fecha.")
    ap.add_argument("--n-iter", type=int, default=6, help="Combinaciones por modelo en la busqueda.")
    ap.add_argument("--cv", type=int, default=3, help="Folds de TimeSeriesSplit.")
    ap.add_argument("--rapido", action="store_true", help="n-iter=2, cv=2 (solo para probar).")
    ap.add_argument("--n-jobs", type=int, default=-1)
    ap.add_argument("--incluir-dias-incompletos", action="store_true")
    args = ap.parse_args()
    if args.rapido:
        args.n_iter, args.cv = 2, 2

    cols = json.loads((args.datos_dir / "columnas.json").read_text(encoding="utf-8"))
    tablas = {
        "turno_dia": pd.read_csv(args.datos_dir / "turno_dia.csv", parse_dates=["Fecha"]),
        "ciclos": pd.read_csv(args.datos_dir / "ciclos.csv", parse_dates=["Fecha"]),
    }
    ci_all = tablas["ciclos"].copy()
    for k, df in tablas.items():
        if not args.incluir_dias_incompletos:
            df = df[df["dia_incompleto"] == 0]
        if args.desde:
            df = df[df["Fecha"] >= args.desde]
        tablas[k] = df.sort_values(["Fecha", "Turno"]).reset_index(drop=True)

    fechas = np.sort(tablas["turno_dia"]["Fecha"].unique())
    corte = pd.Timestamp(args.corte) if args.corte else pd.Timestamp(fechas[int(len(fechas) * 0.8)])
    lim = corte - pd.Timedelta(days=GAP_DIAS)
    print(f"Test: desde {corte.date()} | train: hasta {lim.date()} (gap {GAP_DIAS} dias)\n")

    args.modelo_dir.mkdir(parents=True, exist_ok=True)
    filas_test, filas_cv = [], []
    mejores: dict[str, object] = {}

    for target, (tabla, prev) in TARGETS.items():
        df = tablas[tabla]
        feats = cols["features_turno_dia"] if tabla == "turno_dia" else cols["features_ciclo"]
        tr, te = df[df["Fecha"] < lim], df[df["Fecha"] >= corte]
        Xtr, ytr, Xte, yte = tr[feats], tr[target], te[feats], te[target]
        keys = ["turno_num"] if tabla == "turno_dia" else ["Turno", "Ciclo", "n_ciclos"]
        es_conteo = target == "n_ciclos"
        print(f"=== {target}: train={len(tr)}  test={len(te)}  features={len(feats)} ===")

        # referencia
        base = persistencia(tr, te, target, prev, keys)
        filas_test.append({"target": target, "modelo": "Persistencia(ayer)", **metricas(yte, base, es_conteo)})
        pred_df = te[["Fecha", "Turno", *(["Ciclo"] if tabla == "ciclos" else [])]].copy()
        pred_df["observado"] = yte.values
        pred_df["Persistencia(ayer)"] = base

        best_name, best_cv, best_est = None, np.inf, None
        for name, (est, space) in modelos(args.n_jobs).items():
            t0 = time.time()
            search = RandomizedSearchCV(
                est, space, n_iter=min(args.n_iter, int(np.prod([len(v) for v in space.values()]))),
                cv=TimeSeriesSplit(n_splits=args.cv, gap=20), scoring="neg_root_mean_squared_error",
                random_state=SEED, n_jobs=args.n_jobs if name in ("SVR", "MLP") else 1, refit=True,
            )
            search.fit(Xtr, ytr)
            pred = search.predict(Xte)
            cv_rmse = -search.best_score_
            filas_cv.append({"target": target, "modelo": name, "RMSE_cv": cv_rmse,
                             "params": str(search.best_params_)})
            filas_test.append({"target": target, "modelo": name, **metricas(yte, pred, es_conteo)})
            pred_df[name] = pred
            print(f"  {name:<13} RMSE_cv={cv_rmse:8.3f}  RMSE_test={metricas(yte, pred)['RMSE']:8.3f}  ({time.time() - t0:.0f}s)")
            if cv_rmse < best_cv:  # el mejor se elige SOLO con CV (no con el test)
                best_name, best_cv, best_est = name, cv_rmse, search.best_estimator_
        print(f"  -> mejor por CV: {best_name}\n")
        pred_df.to_csv(args.modelo_dir / f"predicciones_test_{target}.csv", index=False)
        # reajuste del mejor (mismos hiperparametros) con TODO el periodo -> uso real
        best_full = clone(best_est).fit(df[feats], df[target])
        joblib.dump(best_full, args.modelo_dir / f"modelo_{target}.joblib")
        mejores[target] = (best_name, best_full, tabla, feats)

    # ---- fin_min derivado (inicio + duracion) con los mejores modelos, en test
    # (usa las predicciones de test hechas por modelos entrenados solo con train)
    ci = tablas["ciclos"]
    te = ci[ci["Fecha"] >= corte]
    piezas = {t: pd.read_csv(args.modelo_dir / f"predicciones_test_{t}.csv")[mejores[t][0]].to_numpy()
              for t in ("inicio_min", "duracion_min")}
    filas_test.append({"target": "fin_min (derivado)", "modelo": "mejores por CV",
                       **metricas(te["fin_min"].to_numpy(), piezas["inicio_min"] + piezas["duracion_min"])})

    res_test = pd.DataFrame(filas_test)
    res_cv = pd.DataFrame(filas_cv)
    orden = ["target", "modelo", "RMSE", "MAE", "R2", "MBE", "r", "KGE", "NSE", "Willmott_d",
             "NRMSE_%", "MAPE_%", "Spearman_rho", "KGE_alpha", "KGE_beta", "Acierto_exacto", "Acierto_+-1", "n"]
    res_test = res_test[[c for c in orden if c in res_test.columns]]
    res_test.to_csv(args.modelo_dir / "metricas_test.csv", index=False)
    res_cv.to_csv(args.modelo_dir / "metricas_cv.csv", index=False)
    with pd.ExcelWriter(args.modelo_dir / "metricas.xlsx") as w:
        res_test.round(4).to_excel(w, sheet_name="Test", index=False)
        res_cv.to_excel(w, sheet_name="CV_y_parametros", index=False)

    # ---- paquete para predecir_plan
    bundle = {
        "modelos": {t: m[1] for t, m in mejores.items()},
        "elegidos": {t: m[0] for t, m in mejores.items()},
        "features_turno_dia": cols["features_turno_dia"], "features_ciclo": cols["features_ciclo"],
        "max_ciclos": int(tablas["turno_dia"]["n_ciclos"].max()),
        "rango": {"riego_m3ha": (float(ci["riego_m3ha"].min()), float(ci["riego_m3ha"].max())),
                  "duracion_min": (float(ci["duracion_min"].min()), float(ci["duracion_min"].max()))},
    }
    joblib.dump(bundle, args.modelo_dir / "modelo_riego.joblib")

    pd.set_option("display.width", 220)
    print("=== RESULTADOS EN TEST (RMSE / MAE / R2 / MBE / r / KGE) ===")
    print(res_test[["target", "modelo", "RMSE", "MAE", "R2", "MBE", "r", "KGE"]].round(3).to_string(index=False))
    print(f"\nMejores por CV: {bundle['elegidos']}")
    print(f"Guardado en {args.modelo_dir}")


if __name__ == "__main__":
    main()
