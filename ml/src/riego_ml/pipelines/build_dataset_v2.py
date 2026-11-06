#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_dataset.py  (v2, listo para entrenar)
===========================================
Construye el dataset de entrenamiento para predecir, ANTES de que empiece el
dia, el plan de riego de cada turno:

    fecha, turno, n_ciclos y, por cada ciclo: m3/ha, duracion, hora inicio y fin.

Principio clave: ninguna variable de entrada (X) usa informacion posterior a
las 00:00 del dia que se quiere planificar. Asi el modelo entrenado se puede
usar en la vida real.

    - Suelo : ultima lectura horaria disponible a las 23:00 del dia anterior
              (suavizada con las 3 ultimas horas) y su cambio en 24 h.
    - Planta: valores del dia anterior (lag 1) y media de los 3 dias previos.
    - Meteo : valores del dia anterior, acumulados de 3 dias previos.
              (opcional --incluir-meteo-dia: agrega meteo del mismo dia, solo
               valido si en produccion vas a tener un pronostico confiable).
    - Riego : lo regado el dia anterior y el promedio de 3 dias en el mismo
              turno (autorregresivo).

Salidas (en --salida-dir, por defecto ml/data/processed/):
    dataset_riego_MOD5.xlsx : hojas Turno_dia, Ciclos, Diagnostico, Diccionario
    turno_dia.csv           : 1 fila por turno-dia  (target: n_ciclos)
    ciclos.csv              : 1 fila por ciclo      (targets: m3/ha, inicio, duracion)
    columnas.json           : listas de columnas (features / targets) para train_model.py

Uso
---
    python build_dataset.py
    python build_dataset.py --riego r.xlsx --meteo m.xlsx --phytech p.xlsx --salida-dir out/
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# --------------------------------------------------------------------------- #
# Rutas y constantes
# --------------------------------------------------------------------------- #
ML_ROOT = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) > 3 else Path.cwd()
RAW_DIR = ML_ROOT / "data" / "raw"
OUT_DIR = ML_ROOT / "data" / "processed"

PROJECT_ID = 907557  # sensor Phytech conectado a la valvula 21828

# Reglas de limpieza (ajustables)
MIN_DUR_CICLO_MIN = 1.0      # ciclos con menos minutos = apertura fallida
LECTURAS_DIA = 48            # meteo cada 30 min
MIN_LECTURAS_DIA = 36        # dias con menos del 75 % de lecturas -> ETO/Lluvia = NaN
T_MIN_VALIDA = 5.0           # T <= 5 C es error de sensor en este fundo
HR_MIN_VALIDA = 5.0          # HR <= 5 % o > 100 % es error de sensor
HUM_MIN_VALIDA = 5.0         # humedad volumetrica < 5 % se considera error de sonda
SOIL_SMOOTH_H = 3            # suavizado (horas hacia atras) de la lectura de suelo
SOIL_TOLERANCIA_H = 6        # maxima antiguedad aceptada de la lectura de suelo
CICLO_LARGO_MIN = 240        # solo para diagnostico

SOIL_DEPTHS = ["hum_15cm", "hum_30cm", "hum_45cm", "hum_60cm", "hum_75cm", "hum_90cm"]
SOIL_H_COLS = [*SOIL_DEPTHS, "hum_zona_radicular", "hum_linea_estres"]
PLANT_COLUMNS = ["mds_contraccion_um", "crecimiento_tronco_um", "estres_planta_ps"]
METEO_COLUMNS = ["T_mean", "T_max", "T_min", "HR_mean", "HR_max", "ETO", "DPV",
                 "Viento", "Lluvia", "RadSolar_max"]

KEYS_TD = ["Fecha", "Fundo", "Modulo", "Turno"]


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def _norm_text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def _to_seconds(value: object) -> float:
    """datetime.time, datetime o texto HH:MM[:SS] -> segundos del dia."""
    if value is None:
        return np.nan
    try:
        if pd.isna(value):
            return np.nan
    except (TypeError, ValueError):
        pass
    if isinstance(value, (dt.datetime, pd.Timestamp, dt.time)):
        return (value.hour * 3600 + value.minute * 60 + value.second
                + value.microsecond / 1_000_000)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return np.nan
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return np.nan
    return parsed.hour * 3600 + parsed.minute * 60 + parsed.second + parsed.microsecond / 1e6


def fmt_hhmm(minutes: float) -> str:
    """Minutos desde las 00:00 del dia de inicio -> 'HH:MM' (modulo 24 h)."""
    if pd.isna(minutes):
        return ""
    m = int(round(minutes)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


# --------------------------------------------------------------------------- #
# 1. RIEGO  (tabla base)
# --------------------------------------------------------------------------- #
def load_riego(path: Path, sheet: str = "MOD5") -> tuple[pd.DataFrame, dict]:
    df = pd.read_excel(path, sheet_name=sheet).copy()
    diag: dict = {"ciclos_originales": len(df)}

    df["Fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.normalize()
    df["Fundo"] = _norm_text(df["Fundo"])
    df["Modulo"] = _norm_text(df["Modulo"])
    df["Turno"] = _norm_text(df["Turno"])
    df["s_ini"] = df["Hora Inicio"].map(_to_seconds)
    df["s_fin"] = df["Hora Fin"].map(_to_seconds)
    df = df.dropna(subset=["Fecha", "Fundo", "Turno", "s_ini", "s_fin"]).copy()

    df["dt_inicio"] = df["Fecha"] + pd.to_timedelta(df["s_ini"], unit="s")
    df["dt_fin"] = df["Fecha"] + pd.to_timedelta(df["s_fin"], unit="s")
    cruza = df["s_fin"] < df["s_ini"]
    df.loc[cruza, "dt_fin"] += pd.Timedelta(days=1)

    df["duracion_min"] = (df["dt_fin"] - df["dt_inicio"]).dt.total_seconds() / 60.0
    df["riego_m3"] = pd.to_numeric(df["Cantidad de riego (m3)"], errors="coerce")
    df["riego_m3ha"] = pd.to_numeric(df["Cantidad de riego (m3 por hectarea)"], errors="coerce")

    # --- limpieza: aperturas fallidas (duracion ~0 o volumen 0)
    malo = (df["duracion_min"] < MIN_DUR_CICLO_MIN) | (df["riego_m3ha"].fillna(0) <= 0)
    diag["ciclos_descartados_fallidos"] = int(malo.sum())
    df = df[~malo].copy()
    diag["ciclos_largos_>%dmin (se conservan)" % CICLO_LARGO_MIN] = int(
        (df["duracion_min"] > CICLO_LARGO_MIN).sum()
    )

    df = df.sort_values(["Fecha", "Turno", "dt_inicio"]).reset_index(drop=True)
    g = df.groupby(["Fecha", "Turno"], sort=False)
    df["Ciclo"] = g.cumcount() + 1
    df["n_ciclos"] = g["Ciclo"].transform("max")

    # minutos desde las 00:00 del dia de INICIO (fin puede pasar de 1440)
    df["inicio_min"] = (df["dt_inicio"] - df["Fecha"]).dt.total_seconds() / 60.0
    df["fin_min"] = (df["dt_fin"] - df["Fecha"]).dt.total_seconds() / 60.0
    df["hora_inicio"] = df["inicio_min"].map(fmt_hhmm)
    df["hora_fin"] = df["fin_min"].map(fmt_hhmm)
    df["fin_dia_siguiente"] = (df["fin_min"] >= 1440).astype(int)

    diag["ciclos_validos"] = len(df)
    return df, diag


# --------------------------------------------------------------------------- #
# 2. METEO  (limpieza a 30 min -> agregado diario)
# --------------------------------------------------------------------------- #
def load_meteo(path: Path, sheet: str = "Sheet1") -> tuple[pd.DataFrame, dict]:
    df = pd.read_excel(path, sheet_name=sheet, header=2).copy()
    df["Fundo"] = _norm_text(df["Fundo"])
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["Fundo", "Fecha"]).copy()

    diag = {}
    # --- valores imposibles -> NaN (no se rellenan)
    bad_t = df["T° Prom"] <= T_MIN_VALIDA
    df.loc[bad_t, ["T° Prom", "T° Máx", "T° Mín"]] = np.nan
    bad_hr = (df["%HR Prom"] > 100) | (df["%HR Max"] > 100) | (df["%HR Prom"] <= HR_MIN_VALIDA)
    df.loc[bad_hr, ["%HR Prom", "%HR Max"]] = np.nan
    bad_dpv = df["DPV"] < 0
    df.loc[bad_dpv, "DPV"] = np.nan
    diag["meteo_lecturas_T_invalidas"] = int(bad_t.sum())
    diag["meteo_lecturas_HR_invalidas"] = int(bad_hr.sum())
    diag["meteo_lecturas_DPV_negativo"] = int(bad_dpv.sum())

    daily = (
        df.groupby(["Fundo", "Fecha"], as_index=False)
        .agg(
            n_lecturas=("Hora", "size"),
            T_mean=("T° Prom", "mean"),
            T_max=("T° Máx", "max"),
            T_min=("T° Mín", "min"),
            HR_mean=("%HR Prom", "mean"),
            HR_max=("%HR Max", "max"),
            ETO_sum=("ETO", "sum"),
            ETO_n=("ETO", "count"),
            DPV=("DPV", "mean"),
            Viento=("Viento", "mean"),
            Lluvia_sum=("Lluvia", "sum"),
            Lluvia_n=("Lluvia", "count"),
            RadSolar_max=("Rad Solar Max", "max"),
        )
    )
    # ETO: si faltan lecturas se reescala; con muy pocas lecturas -> NaN
    daily["ETO"] = np.where(
        daily["ETO_n"] >= MIN_LECTURAS_DIA,
        daily["ETO_sum"] / daily["ETO_n"].replace(0, np.nan) * LECTURAS_DIA,
        np.nan,
    )
    daily["Lluvia"] = np.where(daily["Lluvia_n"] >= MIN_LECTURAS_DIA, daily["Lluvia_sum"], np.nan)
    diag["meteo_dias_incompletos_ETO_NaN"] = int((daily["ETO_n"] < MIN_LECTURAS_DIA).sum())
    return daily[["Fundo", "Fecha", *METEO_COLUMNS]], diag


# --------------------------------------------------------------------------- #
# 3. PHYTECH  (suelo horario + planta diaria)
# --------------------------------------------------------------------------- #
def load_phytech(path: Path, project_id: int) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    diag = {}
    h = pd.read_excel(path, sheet_name="Suelo_horario")
    h = h[h["project_id"] == project_id].copy()
    h["Fundo"] = _norm_text(h["fundo"])
    h["fecha_hora"] = pd.to_datetime(h["fecha_hora"], errors="coerce")
    h = h.dropna(subset=["Fundo", "fecha_hora"]).sort_values(["Fundo", "fecha_hora"])

    # humedades < 5 % = sonda sin contacto / error (se anulan, no se interpolan)
    malas = 0
    for c in SOIL_DEPTHS:
        m = h[c] < HUM_MIN_VALIDA
        malas += int(m.sum())
        h.loc[m, c] = np.nan
    diag["suelo_lecturas_<5%_anuladas"] = malas

    # suavizado causal (solo horas pasadas) para no depender de una hora suelta vacia
    h[SOIL_H_COLS] = h.groupby("Fundo")[SOIL_H_COLS].transform(
        lambda s: s.rolling(SOIL_SMOOTH_H, min_periods=1).mean()
    )
    soil_h = h[["Fundo", "fecha_hora", *SOIL_H_COLS]].reset_index(drop=True)

    p = pd.read_excel(path, sheet_name="Planta_diario")
    p = p[p["project_id"] == project_id].copy()
    p["Fundo"] = _norm_text(p["fundo"])
    p["Fecha"] = pd.to_datetime(p["fecha"], errors="coerce").dt.normalize()
    p = p.dropna(subset=["Fundo", "Fecha"])
    plant = p[["Fundo", "Fecha", *PLANT_COLUMNS]].drop_duplicates(["Fundo", "Fecha"], keep="last")
    return soil_h, plant, diag


# --------------------------------------------------------------------------- #
# 4. FEATURES (todas "conocidas a las 00:00" del dia a planificar)
# --------------------------------------------------------------------------- #
def soil_snapshot(keys: pd.DataFrame, soil_h: pd.DataFrame, offset_h: int, suffix: str) -> pd.DataFrame:
    """Ultima lectura de suelo con fecha_hora <= (Fecha 00:00 - offset_h)."""
    left = keys[["Fundo", "Fecha"]].drop_duplicates().copy()
    left["ts"] = left["Fecha"] - pd.Timedelta(hours=offset_h)
    left = left.sort_values("ts")
    right = soil_h.sort_values("fecha_hora")
    m = pd.merge_asof(
        left, right, left_on="ts", right_on="fecha_hora", by="Fundo",
        direction="backward", tolerance=pd.Timedelta(hours=SOIL_TOLERANCIA_H),
    )
    ok = m["fecha_hora"].notna()
    assert (m.loc[ok, "fecha_hora"] <= m.loc[ok, "ts"]).all(), "fuga temporal en suelo"
    m = m.drop(columns=["ts", "fecha_hora"])
    return m.rename(columns={c: f"{c}{suffix}" for c in SOIL_H_COLS})


def daily_lag_features(meteo: pd.DataFrame, plant: pd.DataFrame, incluir_dia: bool) -> pd.DataFrame:
    frames = []
    for fundo, m in meteo.groupby("Fundo"):
        pl = plant[plant["Fundo"] == fundo]
        start = min(m["Fecha"].min(), pl["Fecha"].min()) if len(pl) else m["Fecha"].min()
        idx = pd.date_range(start, m["Fecha"].max(), freq="D")
        m = m.set_index("Fecha").reindex(idx)
        pl = pl.set_index("Fecha").reindex(idx)

        f = pd.DataFrame(index=idx)
        for c in METEO_COLUMNS:
            f[f"{c}_d1"] = m[c].shift(1)
        for lag in (2, 3):
            f[f"ETO_d{lag}"] = m["ETO"].shift(lag)
            f[f"Lluvia_d{lag}"] = m["Lluvia"].shift(lag)
        f["ETO_acum3"] = m["ETO"].shift(1).rolling(3, min_periods=3).sum()
        f["Lluvia_acum3"] = m["Lluvia"].shift(1).rolling(3, min_periods=3).sum()

        for c in PLANT_COLUMNS:
            f[f"{c}_d1"] = pl[c].shift(1)
        f["mds_media3"] = pl["mds_contraccion_um"].shift(1).rolling(3, min_periods=2).mean()

        if incluir_dia:
            for c in METEO_COLUMNS:
                f[f"{c}_dia"] = m[c]

        f["Fundo"] = fundo
        f.index.name = "Fecha"
        frames.append(f.reset_index())
    out = pd.concat(frames, ignore_index=True)
    out["Fundo"] = _norm_text(out["Fundo"])
    return out


def riego_lag_features(td: pd.DataFrame) -> pd.DataFrame:
    """Lo regado el dia anterior en el mismo turno (autorregresivo)."""
    frames = []
    for (fundo, turno), g in td.groupby(["Fundo", "Turno"]):
        g = g.set_index("Fecha").sort_index()
        idx = pd.date_range(g.index.min(), g.index.max(), freq="D")
        g = g.reindex(idx)
        f = pd.DataFrame(index=idx)
        f["prev_n_ciclos"] = g["n_ciclos"].shift(1)
        f["prev_riego_total_m3ha"] = g["riego_total_m3ha"].shift(1)
        f["prev_duracion_total_min"] = g["duracion_total_min"].shift(1)
        f["prev3_riego_total_m3ha"] = g["riego_total_m3ha"].shift(1).rolling(3, min_periods=2).mean()
        f["n_ciclos_d2"] = g["n_ciclos"].shift(2)
        f["n_ciclos_d3"] = g["n_ciclos"].shift(3)
        f["n_ciclos_media3"] = g["n_ciclos"].shift(1).rolling(3, min_periods=2).mean()
        f["prev_inicio_primer_min"] = g["inicio_primer_min"].shift(1)
        f["prev_fin_ultimo_min"] = g["fin_ultimo_min"].shift(1)
        f["Fundo"], f["Turno"] = fundo, turno
        f.index.name = "Fecha"
        frames.append(f.reset_index())
    out = pd.concat(frames, ignore_index=True)
    out["Fundo"] = _norm_text(out["Fundo"])
    out["Turno"] = _norm_text(out["Turno"])
    return out


# --------------------------------------------------------------------------- #
# 5. ENSAMBLADO
# --------------------------------------------------------------------------- #
def build(riego, meteo, soil_h, plant, incluir_dia):
    # ---- tabla turno-dia (base de features)
    g = riego.groupby(KEYS_TD, as_index=False)
    td = g.agg(
        n_ciclos=("Ciclo", "max"),
        riego_total_m3ha=("riego_m3ha", "sum"),
        duracion_total_min=("duracion_min", "sum"),
        inicio_primer_min=("inicio_min", "min"),
        fin_ultimo_min=("fin_min", "max"),
    )
    td["turno_num"] = td["Turno"].str.extract(r"(\d+)").astype(float)

    # ---- features calendario
    doy = td["Fecha"].dt.dayofyear
    td["mes"] = td["Fecha"].dt.month
    td["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    td["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)

    # ---- meteo + planta (lags)
    dl = daily_lag_features(meteo, plant, incluir_dia)
    td = td.merge(dl, on=["Fundo", "Fecha"], how="left", validate="many_to_one")

    # ---- suelo (instantanea a las 23:00 del dia anterior y cambio en 24 h)
    s0 = soil_snapshot(td, soil_h, offset_h=1, suffix="_ini")
    s1 = soil_snapshot(td, soil_h, offset_h=25, suffix="_prev")
    td = td.merge(s0, on=["Fundo", "Fecha"], how="left", validate="many_to_one")
    td = td.merge(
        s1[["Fundo", "Fecha", "hum_zona_radicular_prev", "hum_45cm_prev"]],
        on=["Fundo", "Fecha"], how="left", validate="many_to_one",
    )
    td["d_hum_zona_24h"] = td["hum_zona_radicular_ini"] - td["hum_zona_radicular_prev"]
    td["d_hum_45cm_24h"] = td["hum_45cm_ini"] - td["hum_45cm_prev"]
    td["dist_linea_estres_ini"] = td["hum_zona_radicular_ini"] - td["hum_linea_estres_ini"]
    td = td.drop(columns=["hum_zona_radicular_prev", "hum_45cm_prev"])

    # ---- riego previo
    rl = riego_lag_features(td)
    td = td.merge(rl, on=["Fundo", "Turno", "Fecha"], how="left", validate="one_to_one")

    # ---- calidad del dia
    turnos_dia = td.groupby("Fecha")["Turno"].transform("nunique")
    td["dia_incompleto"] = (turnos_dia < td["Turno"].nunique()).astype(int)

    td = td.sort_values(["Fecha", "Turno"]).reset_index(drop=True)

    meta = ["Fecha", "Fundo", "Modulo", "Turno"]
    extra_no_feature = ["riego_total_m3ha", "duracion_total_min", "dia_incompleto",
                        "inicio_primer_min", "fin_ultimo_min"]
    features = [c for c in td.columns if c not in meta + ["n_ciclos"] + extra_no_feature]

    # ---- tabla de ciclos
    ciclos = riego[[*KEYS_TD, "Ciclo", "n_ciclos", "riego_m3ha", "duracion_min",
                    "inicio_min", "fin_min", "hora_inicio", "hora_fin",
                    "fin_dia_siguiente"]].merge(
        td[[*KEYS_TD, *features, "dia_incompleto"]],
        on=KEYS_TD, how="left", validate="many_to_one",
    )
    pc = riego[["Fecha", "Turno", "Ciclo", "riego_m3ha", "inicio_min", "duracion_min", "fin_min"]].copy()
    pc["Fecha"] = pc["Fecha"] + pd.Timedelta(days=1)  # lo ocurrido AYER pasa a ser dato de HOY
    pc = pc.rename(columns={"riego_m3ha": "prev_m3ha_ciclo", "inicio_min": "prev_inicio_ciclo",
                            "duracion_min": "prev_dur_ciclo", "fin_min": "prev_fin_ciclo"})
    ciclos = ciclos.merge(pc, on=["Fecha", "Turno", "Ciclo"], how="left", validate="one_to_one")
    ciclos = ciclos.sort_values(["Fecha", "Turno", "Ciclo"]).reset_index(drop=True)
    prev_ciclo_cols = ["prev_m3ha_ciclo", "prev_inicio_ciclo", "prev_dur_ciclo", "prev_fin_ciclo"]

    cols = {
        "meta": meta,
        "features_turno_dia": features,
        "features_ciclo": [*features, "Ciclo", "n_ciclos", *prev_ciclo_cols],
        "target_turno_dia": "n_ciclos",
        "targets_ciclo": ["riego_m3ha", "inicio_min", "duracion_min"],
        "derivados": ["fin_min", "hora_inicio", "hora_fin"],
    }
    return td, ciclos, cols


# --------------------------------------------------------------------------- #
# 6. DIAGNOSTICO, DICCIONARIO Y EXCEL
# --------------------------------------------------------------------------- #
def build_diagnostico(td, ciclos, cols, diag):
    feats = cols["features_turno_dia"]
    rows = [(k, v) for k, v in diag.items()]
    rows += [
        ("turno_dias", len(td)),
        ("ciclos", len(ciclos)),
        ("fecha_min", td["Fecha"].min().date()),
        ("fecha_max", td["Fecha"].max().date()),
        ("dias_incompletos (<5 turnos)", int(td.groupby("Fecha")["dia_incompleto"].max().sum())),
        ("n_features_turno_dia", len(feats)),
    ]
    for c in ["hum_zona_radicular_ini", "hum_45cm_ini", "hum_15cm_ini",
              "mds_contraccion_um_d1", "ETO_d1", "ETO_acum3", "prev_riego_total_m3ha"]:
        rows.append((f"% turno-dias con {c}", f"{td[c].notna().mean() * 100:.1f}%"))
    rows.append(("turno-dias con TODO suelo+planta+meteo+riego previo",
                 int(td[["hum_zona_radicular_ini", "mds_contraccion_um_d1", "ETO_d1",
                         "prev_riego_total_m3ha"]].notna().all(axis=1).sum())))
    rows.append(("n_ciclos distribucion", td["n_ciclos"].value_counts().sort_index().to_dict().__str__()))
    return pd.DataFrame(rows, columns=["Metrica", "Valor"]).astype({"Valor": "string"})


def build_diccionario(cols, incluir_dia):
    d = {
        "Fecha": "Fecha de inicio del riego (dia a planificar).",
        "Turno": "Turno de riego TE01..TE05.",
        "turno_num": "Numero del turno (1..5).",
        "n_ciclos": "TARGET turno-dia: numero de ciclos de riego del turno ese dia.",
        "Ciclo": "Numero de ciclo dentro del turno-dia (1,2,3...).",
        "riego_m3ha": "TARGET ciclo: volumen del ciclo en m3/ha.",
        "inicio_min": "TARGET ciclo: minutos desde las 00:00 de la Fecha hasta el inicio del ciclo.",
        "duracion_min": "TARGET ciclo: duracion del ciclo en minutos (se deriva de m3/ha / caudal del turno).",
        "fin_min": "Minutos desde las 00:00 de la Fecha hasta el fin (puede superar 1440).",
        "hora_inicio": "HH:MM de inicio.", "hora_fin": "HH:MM de fin.",
        "fin_dia_siguiente": "1 si el ciclo termina al dia siguiente.",
        "riego_total_m3ha": "Suma de m3/ha del turno-dia (informativo, NO es feature).",
        "duracion_total_min": "Suma de minutos del turno-dia (informativo, NO es feature).",
        "dia_incompleto": "1 si ese dia hubo menos de 5 turnos (posible hueco de registro).",
        "mes": "Mes del ano.", "doy_sin": "sin(2*pi*dia_del_anio/365.25).", "doy_cos": "cos(...).",
        "prev_n_ciclos": "Ciclos del mismo turno el dia anterior.",
        "prev_riego_total_m3ha": "m3/ha totales del mismo turno el dia anterior.",
        "prev_duracion_total_min": "Minutos totales del mismo turno el dia anterior.",
        "prev3_riego_total_m3ha": "Media de m3/ha totales del turno en los 3 dias previos.",
        "n_ciclos_d2": "Ciclos del mismo turno hace 2 dias.",
        "n_ciclos_d3": "Ciclos del mismo turno hace 3 dias.",
        "n_ciclos_media3": "Media de ciclos del turno en los 3 dias previos.",
        "prev_inicio_primer_min": "Minuto de inicio del primer ciclo del dia anterior (mismo turno).",
        "prev_fin_ultimo_min": "Minuto de fin del ultimo ciclo del dia anterior (mismo turno).",
        "prev_m3ha_ciclo": "m3/ha del MISMO numero de ciclo el dia anterior (mismo turno).",
        "prev_inicio_ciclo": "Minuto de inicio del mismo numero de ciclo el dia anterior.",
        "prev_dur_ciclo": "Duracion (min) del mismo numero de ciclo el dia anterior.",
        "prev_fin_ciclo": "Minuto de fin del mismo numero de ciclo el dia anterior.",
        "ETO_acum3": "ETO acumulada de los 3 dias previos (mm).",
        "Lluvia_acum3": "Lluvia acumulada de los 3 dias previos (mm).",
        "mds_media3": "Media del MDS de los 3 dias previos (um).",
        "d_hum_zona_24h": "Cambio de la humedad de zona radicular en las 24 h previas (puntos %).",
        "d_hum_45cm_24h": "Cambio de la humedad a 45 cm en las 24 h previas.",
        "dist_linea_estres_ini": "Humedad zona radicular - linea de estres de Phytech (negativo = bajo el umbral).",
    }
    for c in METEO_COLUMNS:
        d[f"{c}_d1"] = f"{c} del dia anterior."
        if incluir_dia:
            d[f"{c}_dia"] = f"{c} del MISMO dia (requiere pronostico en produccion)."
    for lag in (2, 3):
        d[f"ETO_d{lag}"] = f"ETO de hace {lag} dias."
        d[f"Lluvia_d{lag}"] = f"Lluvia de hace {lag} dias."
    for c in PLANT_COLUMNS:
        d[f"{c}_d1"] = f"{c} del dia anterior (sensor 907557)."
    for c in SOIL_H_COLS:
        d[f"{c}_ini"] = f"{c}: lectura de las 23:00 del dia anterior, suavizada 3 h (sensor 907557)."
    rows = [(c, d.get(c, "")) for c in dict.fromkeys(
        [*cols["meta"], "turno_num", "n_ciclos", "Ciclo", *cols["targets_ciclo"], *cols["derivados"],
         "fin_dia_siguiente", "riego_total_m3ha", "duracion_total_min", "dia_incompleto",
         "inicio_primer_min", "fin_ultimo_min", *cols["features_ciclo"],
         *cols["features_turno_dia"]])]
    return pd.DataFrame(rows, columns=["Columna", "Descripcion"])


def write_excel(path: Path, sheets: dict[str, pd.DataFrame]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl", datetime_format="yyyy-mm-dd",
                        date_format="yyyy-mm-dd") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
        fill = PatternFill("solid", start_color="1F4E78")
        for sheet in writer.sheets.values():
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF", name="Arial")
                cell.fill = fill
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            sheet.freeze_panes = "A2"
            if sheet.title in {"Turno_dia", "Ciclos"}:
                sheet.auto_filter.ref = sheet.dimensions
            for column_cells in sheet.columns:
                w = max(len(str(c.value)) if c.value is not None else 0 for c in column_cells[:200])
                sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = min(max(w + 2, 10), 40)


def main() -> None:
    ap = argparse.ArgumentParser(description="Dataset de entrenamiento: plan de riego por turno-dia.")
    ap.add_argument("--riego", type=Path, default=RAW_DIR / "data_riego.xlsx")
    ap.add_argument("--meteo", type=Path, default=RAW_DIR / "data_metereologica.xlsx")
    ap.add_argument("--phytech", type=Path, default=RAW_DIR / "data_phytech.xlsx")
    ap.add_argument("--salida-dir", type=Path, default=OUT_DIR)
    ap.add_argument("--project-id", type=int, default=PROJECT_ID)
    ap.add_argument("--incluir-meteo-dia", action="store_true",
                    help="Agrega meteo del mismo dia (solo si en produccion tendras pronostico).")
    args = ap.parse_args()

    diag: dict = {}
    print("Leyendo riego...")
    riego, d = load_riego(args.riego); diag.update(d)
    print(f"  {d['ciclos_originales']} ciclos -> {d['ciclos_validos']} validos "
          f"({d['ciclos_descartados_fallidos']} fallidos descartados)")

    print("Leyendo meteo...")
    meteo, d = load_meteo(args.meteo); diag.update(d)

    print(f"Leyendo Phytech (sensor {args.project_id})...")
    soil_h, plant, d = load_phytech(args.phytech, args.project_id); diag.update(d)

    print("Construyendo features...")
    td, ciclos, cols = build(riego, meteo, soil_h, plant, args.incluir_meteo_dia)

    diagnostico = build_diagnostico(td, ciclos, cols, diag)
    diccionario = build_diccionario(cols, args.incluir_meteo_dia)

    out = args.salida_dir
    out.mkdir(parents=True, exist_ok=True)
    td.to_csv(out / "turno_dia.csv", index=False)
    ciclos.to_csv(out / "ciclos.csv", index=False)
    (out / "columnas.json").write_text(json.dumps(cols, indent=2, ensure_ascii=False), encoding="utf-8")
    write_excel(out / "dataset_riego_MOD5_V2.xlsx", {
        "Turno_dia": td, "Ciclos": ciclos, "Diagnostico": diagnostico, "Diccionario": diccionario,
    })

    print("\nListo.")
    print(f"  Turno-dia : {td.shape[0]} filas x {td.shape[1]} columnas "
          f"({len(cols['features_turno_dia'])} features)")
    print(f"  Ciclos    : {ciclos.shape[0]} filas")
    print(f"  Salida    : {out}")


if __name__ == "__main__":
    main()
