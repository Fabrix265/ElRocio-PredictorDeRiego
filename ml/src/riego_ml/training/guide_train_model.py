#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
train_model.py
==============
Entrena el modelo que, para cada turno y dia, devuelve el plan de riego:

    Fecha, Turno, n_ciclos y, por cada ciclo: m3/ha, duracion (min),
    hora de inicio y hora de fin.

Diseno
------
Tres salidas se predicen: n_ciclos, riego_m3ha (por ciclo) e inicio_min (por
ciclo). La duracion y la hora de fin se DERIVAN para que todo sea coherente:
    duracion = m3/ha / caudal_turno        fin = inicio + duracion

Para cada salida se comparan varios candidatos:
    persistencia : lo que hizo el mismo turno/ciclo el dia anterior
    mediana      : mediana historica por turno / ciclo / n_ciclos
    hgb_directo  : gradient boosting sobre las features
    hgb_delta    : gradient boosting que predice el CAMBIO respecto a ayer
El ganador se elige con una validacion temporal interna (ultimo 15 % del
periodo de entrenamiento). Las metricas finales se miden en un test temporal
que el modelo nunca vio. Si el ML no supera a la persistencia, el script usa la
persistencia y lo dice: no se fuerza un modelo que no aporta.

Uso
---
    python train_model.py
    python train_model.py --datos-dir ml/data/processed --corte 2024-06-01
    python train_model.py --desde 2023-10-01     # solo periodo con suelo completo
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

ML_ROOT = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) > 3 else Path.cwd()
GAP_DIAS = 3
PAUSA_MIN = 10  # pausa minima entre ciclos del mismo turno


def make_model() -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(
        max_iter=150, learning_rate=0.05, max_leaf_nodes=7, min_samples_leaf=60,
        l2_regularization=1.0, early_stopping=False, random_state=42,
    )


def mae(a, b) -> float:
    return float(np.mean(np.abs(np.asarray(a, float) - np.asarray(b, float))))


def fmt_hhmm(minutes: float) -> str:
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


# --------------------------------------------------------------------------- #
# Candidatos (solo dicts + modelos sklearn => el .joblib se carga en cualquier lado)
# --------------------------------------------------------------------------- #
def _key_index(X: pd.DataFrame, keys: list[str]):
    return pd.MultiIndex.from_frame(X[keys]) if len(keys) > 1 else pd.Index(X[keys[0]])


def _tab_predict(spec: dict, X: pd.DataFrame) -> np.ndarray:
    v = spec["tab"].reindex(_key_index(X, spec["keys"])).to_numpy(float)
    return np.where(np.isnan(v), spec["glob"], v)


def fit_spec(tipo: str, X: pd.DataFrame, y: pd.Series, keys: list[str],
             feats: list[str] | None = None, prev: str | None = None) -> dict:
    spec = {"tipo": tipo, "keys": keys, "feats": feats, "prev": prev,
            "glob": float(y.median())}
    spec["tab"] = y.groupby([X[k] for k in keys]).median()  # respaldo siempre disponible
    if tipo == "hgb_directo":
        spec["model"] = make_model().fit(X[feats], y)
    elif tipo == "hgb_delta":
        ok = X[prev].notna()
        spec["model"] = make_model().fit(X.loc[ok, feats], (y - X[prev])[ok])
    return spec


def predict_spec(spec: dict, X: pd.DataFrame) -> np.ndarray:
    t, fb = spec["tipo"], _tab_predict(spec, X)
    if t == "mediana":
        return fb
    if t == "persistencia":
        return np.where(X[spec["prev"]].notna(), X[spec["prev"]].to_numpy(float), fb)
    if t == "hgb_directo":
        return spec["model"].predict(X[spec["feats"]])
    if t == "hgb_delta":
        prev = X[spec["prev"]].to_numpy(float)
        return np.where(~np.isnan(prev), prev + spec["model"].predict(X[spec["feats"]]), fb)
    raise ValueError(t)


def candidatos(target: str, cols: dict) -> dict[str, dict]:
    f_td, f_ci = cols["features_turno_dia"], cols["features_ciclo"]
    eto = ["ETO_d1", "ETO_acum3", "Lluvia_acum3", "T_mean_d1", "mes", "turno_num"]
    if target == "n_ciclos":
        compact = ["prev_n_ciclos", "n_ciclos_media3", *eto, "hum_zona_radicular_ini",
                   "dist_linea_estres_ini", "mds_contraccion_um_d1"]
        return {
            "persistencia": dict(tipo="persistencia", keys=["turno_num"], prev="prev_n_ciclos"),
            "hgb_directo": dict(tipo="hgb_directo", keys=["turno_num"], feats=f_td),
            "hgb_delta": dict(tipo="hgb_delta", keys=["turno_num"], feats=compact, prev="prev_n_ciclos"),
        }
    key = ["Turno", "Ciclo", "n_ciclos"]
    if target == "riego_m3ha":
        compact = ["Ciclo", "n_ciclos", "prev_m3ha_ciclo", "prev_riego_total_m3ha", *eto]
        return {
            "persistencia": dict(tipo="persistencia", keys=key, prev="prev_m3ha_ciclo"),
            "mediana": dict(tipo="mediana", keys=key),
            "hgb_directo": dict(tipo="hgb_directo", keys=key, feats=f_ci),
            "hgb_delta": dict(tipo="hgb_delta", keys=key, feats=compact, prev="prev_m3ha_ciclo"),
        }
    if target == "inicio_min":
        return {
            "persistencia": dict(tipo="persistencia", keys=key, prev="prev_inicio_ciclo"),
            "mediana": dict(tipo="mediana", keys=key),
            "hgb_directo": dict(tipo="hgb_directo", keys=key, feats=f_ci),
        }
    raise ValueError(target)


def post(target: str, pred: np.ndarray, max_n: int) -> np.ndarray:
    if target == "n_ciclos":
        return np.clip(np.rint(pred), 1, max_n)
    if target == "inicio_min":
        return np.clip(pred, 0, 1439)
    return pred


def elegir_y_ajustar(target: str, df: pd.DataFrame, cols: dict, max_n: int) -> tuple[dict, dict]:
    """Elige el mejor candidato con validacion temporal interna y lo reajusta con todo df."""
    cands = candidatos(target, cols)
    fechas = np.sort(df["Fecha"].unique())
    cut = pd.Timestamp(fechas[int(len(fechas) * 0.85)])
    fit_m = df["Fecha"] < cut - pd.Timedelta(days=GAP_DIAS)
    val_m = df["Fecha"] >= cut
    scores = {}
    for name, c in cands.items():
        sp = fit_spec(X=df[fit_m], y=df.loc[fit_m, target], **c)
        scores[name] = mae(df.loc[val_m, target], post(target, predict_spec(sp, df[val_m]), max_n))
    best = min(scores, key=scores.get)
    spec = fit_spec(X=df, y=df[target], **cands[best])
    spec["nombre"] = best
    return spec, scores


# --------------------------------------------------------------------------- #
# Plan de riego
# --------------------------------------------------------------------------- #
def predecir_plan(bundle: dict, X: pd.DataFrame, hist_ciclos: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    X           : filas turno-dia con 'Fecha','Turno' + features_turno_dia (salida de build_dataset).
    hist_ciclos : ciclos REALES ya ocurridos (ciclos.csv); se usa lo del dia anterior.
    Devuelve una fila por ciclo: Fecha, Turno, n_ciclos, Ciclo, riego_m3ha,
    duracion_min, hora_inicio, hora_fin, fin_dia_siguiente.
    """
    X = X.reset_index(drop=True)
    n_pred = post("n_ciclos", predict_spec(bundle["n_ciclos"], X), bundle["max_ciclos"]).astype(int)

    rep = X.loc[X.index.repeat(n_pred)].copy()
    rep["n_ciclos"] = np.repeat(n_pred, n_pred)
    rep["Ciclo"] = np.concatenate([np.arange(1, n + 1) for n in n_pred])

    prev_cols = ["prev_m3ha_ciclo", "prev_inicio_ciclo", "prev_dur_ciclo", "prev_fin_ciclo"]
    rep = rep.drop(columns=[c for c in prev_cols if c in rep.columns])
    if hist_ciclos is not None:
        pc = hist_ciclos[["Fecha", "Turno", "Ciclo", "riego_m3ha", "inicio_min",
                          "duracion_min", "fin_min"]].copy()
        pc["Fecha"] = pc["Fecha"] + pd.Timedelta(days=1)
        pc = pc.rename(columns=dict(zip(["riego_m3ha", "inicio_min", "duracion_min", "fin_min"], prev_cols)))
        rep = rep.merge(pc, on=["Fecha", "Turno", "Ciclo"], how="left")
    else:
        for c in prev_cols:
            rep[c] = np.nan
    rep = rep.reset_index(drop=True)

    rep["riego_m3ha"] = np.clip(predict_spec(bundle["riego_m3ha"], rep),
                                bundle["m3ha_rango"][0], bundle["m3ha_rango"][1])
    rep["inicio_min"] = post("inicio_min", predict_spec(bundle["inicio_min"], rep), 0)
    rep["duracion_min"] = rep["riego_m3ha"] / rep["Turno"].map(bundle["caudal_m3ha_min"])

    # coherencia: ciclos ordenados y sin solaparse dentro del turno-dia
    rep = rep.sort_values(["Fecha", "Turno", "inicio_min"]).reset_index(drop=True)
    rep["Ciclo"] = rep.groupby(["Fecha", "Turno"]).cumcount() + 1
    inicio, fin = [], []
    for _, g in rep.groupby(["Fecha", "Turno"], sort=False):
        prev_fin = -np.inf
        for ini, dur in zip(g["inicio_min"], g["duracion_min"]):
            ini = max(ini, prev_fin + PAUSA_MIN)
            prev_fin = ini + dur
            inicio.append(ini)
            fin.append(prev_fin)
    rep["inicio_min"], rep["fin_min"] = inicio, fin
    rep["hora_inicio"] = rep["inicio_min"].map(fmt_hhmm)
    rep["hora_fin"] = rep["fin_min"].map(fmt_hhmm)
    rep["fin_dia_siguiente"] = (rep["fin_min"] >= 1440).astype(int)
    out = rep[["Fecha", "Turno", "n_ciclos", "Ciclo", "riego_m3ha", "duracion_min",
               "hora_inicio", "hora_fin", "fin_dia_siguiente", "inicio_min", "fin_min"]]
    return out.round({"riego_m3ha": 2, "duracion_min": 1, "inicio_min": 1, "fin_min": 1}).reset_index(drop=True)


def fit_bundle(td: pd.DataFrame, ci: pd.DataFrame, cols: dict) -> tuple[dict, dict]:
    max_n = int(td["n_ciclos"].max())
    sel, scores = {}, {}
    sel["n_ciclos"], scores["n_ciclos"] = elegir_y_ajustar("n_ciclos", td, cols, max_n)
    sel["riego_m3ha"], scores["riego_m3ha"] = elegir_y_ajustar("riego_m3ha", ci, cols, max_n)
    sel["inicio_min"], scores["inicio_min"] = elegir_y_ajustar("inicio_min", ci, cols, max_n)
    bundle = {
        **sel, "max_ciclos": max_n,
        "caudal_m3ha_min": (ci["riego_m3ha"] / ci["duracion_min"]).groupby(ci["Turno"]).median().to_dict(),
        "m3ha_rango": (float(ci["riego_m3ha"].min()), float(ci["riego_m3ha"].max())),
        "elegidos": {k: v["nombre"] for k, v in sel.items()},
    }
    return bundle, scores


# --------------------------------------------------------------------------- #
# Evaluacion en test (nunca visto)
# --------------------------------------------------------------------------- #
def evaluar(bundle, scores_val, tr_td, tr_ci, te_td, te_ci, ci_all, cols) -> tuple[dict, pd.DataFrame]:
    max_n = bundle["max_ciclos"]
    res = {"filas": {"train_turno_dia": len(tr_td), "test_turno_dia": len(te_td),
                     "train_ciclos": len(tr_ci), "test_ciclos": len(te_ci)},
           "elegidos_por_validacion_interna": bundle["elegidos"],
           "MAE_validacion_interna": scores_val}

    # todos los candidatos medidos en test (informativo; la eleccion NO se hizo aqui)
    for target, df_tr, df_te in [("n_ciclos", tr_td, te_td), ("riego_m3ha", tr_ci, te_ci),
                                 ("inicio_min", tr_ci, te_ci)]:
        out = {}
        for name, c in candidatos(target, cols).items():
            sp = fit_spec(X=df_tr, y=df_tr[target], **c)
            out[name] = round(mae(df_te[target], post(target, predict_spec(sp, df_te), max_n)), 3)
        res.setdefault("MAE_test_todos_los_candidatos", {})[target] = out

    # modelo elegido, dado n_ciclos real
    v = predict_spec(bundle["riego_m3ha"], te_ci)
    d = v / te_ci["Turno"].map(bundle["caudal_m3ha_min"])
    res["ciclo_dado_n_real"] = {
        "MAE_m3ha": round(mae(te_ci["riego_m3ha"], v), 3),
        "MAE_duracion_min": round(mae(te_ci["duracion_min"], d), 2),
        "MAE_inicio_min": round(mae(te_ci["inicio_min"], post("inicio_min", predict_spec(bundle["inicio_min"], te_ci), 0)), 1),
    }

    # n_ciclos
    n_hat = post("n_ciclos", predict_spec(bundle["n_ciclos"], te_td), max_n)
    res["n_ciclos"] = {
        "MAE": round(mae(te_td["n_ciclos"], n_hat), 3),
        "acierto_exacto": round(float((n_hat == te_td["n_ciclos"]).mean()), 3),
        "acierto_+-1": round(float((np.abs(n_hat - te_td["n_ciclos"]) <= 1).mean()), 3),
    }

    # extremo a extremo: plan completo con n_ciclos predicho
    plan = predecir_plan(bundle, te_td[["Fecha", "Turno", *cols["features_turno_dia"]]], hist_ciclos=ci_all)
    tot = plan.groupby(["Fecha", "Turno"])["riego_m3ha"].sum().rename("hat")
    real = te_td.set_index(["Fecha", "Turno"])["riego_total_m3ha"]
    j = pd.concat([real, tot], axis=1).dropna()
    base = te_td.set_index(["Fecha", "Turno"])["prev_riego_total_m3ha"].reindex(j.index)
    base = base.fillna(tr_td["riego_total_m3ha"].median())
    res["total_turno_dia_extremo_a_extremo"] = {
        "MAE_m3ha_plan": round(mae(j["riego_total_m3ha"], j["hat"]), 3),
        "MAE_m3ha_copiar_ayer": round(mae(j["riego_total_m3ha"], base), 3),
        "promedio_real_m3ha": round(float(j["riego_total_m3ha"].mean()), 2),
    }
    return res, plan


def main() -> None:
    ap = argparse.ArgumentParser(description="Entrena el modelo de plan de riego.")
    ap.add_argument("--datos-dir", type=Path, default=ML_ROOT / "data" / "processed")
    ap.add_argument("--modelo-dir", type=Path, default=ML_ROOT / "models")
    ap.add_argument("--corte", type=str, default=None,
                    help="YYYY-MM-DD: desde esa fecha es test. Por defecto el ultimo 20 %% de las fechas.")
    ap.add_argument("--desde", type=str, default=None,
                    help="Usar solo datos desde esta fecha (ej. 2023-10-01 = suelo completo).")
    ap.add_argument("--incluir-dias-incompletos", action="store_true")
    args = ap.parse_args()

    cols = json.loads((args.datos_dir / "columnas.json").read_text(encoding="utf-8"))
    td = pd.read_csv(args.datos_dir / "turno_dia.csv", parse_dates=["Fecha"])
    ci = pd.read_csv(args.datos_dir / "ciclos.csv", parse_dates=["Fecha"])
    ci_all = ci.copy()  # historia real completa (para lags de ciclo en el plan)

    if not args.incluir_dias_incompletos:
        td, ci = td[td["dia_incompleto"] == 0], ci[ci["dia_incompleto"] == 0]
    if args.desde:
        td, ci = td[td["Fecha"] >= args.desde], ci[ci["Fecha"] >= args.desde]

    fechas = np.sort(td["Fecha"].unique())
    corte = pd.Timestamp(args.corte) if args.corte else pd.Timestamp(fechas[int(len(fechas) * 0.8)])
    lim = corte - pd.Timedelta(days=GAP_DIAS)
    print(f"Test temporal: desde {corte.date()}  (train hasta {lim.date()}, gap {GAP_DIAS} dias)\n")
    tr_td, te_td = td[td["Fecha"] < lim], td[td["Fecha"] >= corte]
    tr_ci, te_ci = ci[ci["Fecha"] < lim], ci[ci["Fecha"] >= corte]

    bundle_val, scores_val = fit_bundle(tr_td, tr_ci, cols)
    res, plan_test = evaluar(bundle_val, scores_val, tr_td, tr_ci, te_td, te_ci, ci_all, cols)
    print(json.dumps(res, indent=2, ensure_ascii=False))

    args.modelo_dir.mkdir(parents=True, exist_ok=True)
    (args.modelo_dir / "metricas.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    plan_test.drop(columns=["inicio_min", "fin_min"]).to_csv(args.modelo_dir / "predicciones_test.csv", index=False)

    # modelo final: reentrenado con TODOS los datos (uso real)
    bundle, _ = fit_bundle(td, ci, cols)
    bundle["features_turno_dia"] = cols["features_turno_dia"]
    joblib.dump(bundle, args.modelo_dir / "modelo_riego.joblib")
    print(f"\nModelo final ({bundle['elegidos']}) -> {args.modelo_dir / 'modelo_riego.joblib'}")
    print(f"Plan de prueba -> {args.modelo_dir / 'predicciones_test.csv'}")


if __name__ == "__main__":
    main()
