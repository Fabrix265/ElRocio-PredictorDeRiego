"""Features del plan de riego, todas conocidas a las 00:00 del día a planificar.

Regla anti-fuga: para predecir el día D solo se usa información hasta el día
D-1 (meteo y planta del día anterior, suelo al cierre del día anterior, riego
de días anteriores). La misma función se usa para entrenar y para predecir,
así no hay diferencias entre ambos momentos.

Opcional: ``incluir_meteo_dia`` agrega la meteo del mismo día D; solo tiene
sentido si en producción se va a contar con un pronóstico confiable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from riego_ml.dataset.limpieza import CLAVES_TD, CLAVES_TURNO
from riego_ml.utils.tiempo import MINUTOS_DIA

METEO_D1 = [
    "T_media", "T_max", "T_min", "HR_media", "HR_min", "ETo_mm", "DPV_media",
    "DPV_max", "Viento_media", "Lluvia_mm", "Rad_max", "Rad_media",
]
SUELO_D1 = [
    "hum_15cm", "hum_30cm", "hum_45cm", "hum_60cm", "hum_75cm", "hum_90cm",
    "hum_zona_radicular",
]
PLANTA_D1 = ["mds_contraccion_um", "crecimiento_tronco_um", "estres_planta_ps"]
CATEGORICAS = ["Turno"]


def _rejilla(fechas_min: pd.Timestamp, fechas_max: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(fechas_min, fechas_max, freq="D", name="Fecha")


# --------------------------------------------------------------------------- #
# Ambiente (meteo + suelo + planta)
# --------------------------------------------------------------------------- #
def features_ambiente(
    ambiente: pd.DataFrame, fecha_max: pd.Timestamp, incluir_meteo_dia: bool = False
) -> pd.DataFrame:
    """1 fila por Fundo y día con los rezagos del ambiente."""
    frames = []
    for fundo, a in ambiente.groupby("Fundo"):
        idx = _rejilla(a["Fecha"].min(), max(a["Fecha"].max(), fecha_max))
        a = a.set_index("Fecha").reindex(idx)
        f = pd.DataFrame(index=idx)

        for c in METEO_D1:
            f[f"{c}_d1"] = a[c].shift(1)
        eto = a["ETo_mm"].shift(1)
        f["ETo_mm_d2"] = a["ETo_mm"].shift(2)
        f["ETo_media3"] = eto.rolling(3, min_periods=2).mean()
        f["ETo_media7"] = eto.rolling(7, min_periods=4).mean()
        f["T_max_media3"] = a["T_max"].shift(1).rolling(3, min_periods=2).mean()
        f["Lluvia_acum7"] = a["Lluvia_mm"].shift(1).rolling(7, min_periods=4).sum()

        for c in SUELO_D1:
            f[f"{c}_cierre_d1"] = a[f"{c}_cierre"].shift(1)
        f["dist_linea_estres_d1"] = (
            a["hum_zona_radicular_cierre"] - a["hum_linea_estres_cierre"]
        ).shift(1)
        f["d_hum_zona_24h"] = a["hum_zona_radicular_cierre"].shift(1) - a["hum_zona_radicular_cierre"].shift(2)
        f["d_hum_45cm_24h"] = a["hum_45cm_cierre"].shift(1) - a["hum_45cm_cierre"].shift(2)

        for c in PLANTA_D1:
            f[f"{c}_d1"] = a[c].shift(1)
        f["mds_media3"] = a["mds_contraccion_um"].shift(1).rolling(3, min_periods=2).mean()

        if incluir_meteo_dia:
            for c in METEO_D1:
                f[f"{c}_dia"] = a[c]

        f["Fundo"] = fundo
        frames.append(f.reset_index())
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- #
# Historial de riego del mismo turno
# --------------------------------------------------------------------------- #
def features_riego_previo(turno_dia: pd.DataFrame, fecha_max: pd.Timestamp) -> pd.DataFrame:
    """Rezagos autorregresivos del mismo turno (lo regado días anteriores)."""
    frames = []
    for claves, g in turno_dia.groupby(CLAVES_TURNO):
        idx = _rejilla(g["Fecha"].min(), max(g["Fecha"].max(), fecha_max))
        g = g.set_index("Fecha").reindex(idx)
        f = pd.DataFrame(index=idx)
        n = g["n_ciclos"]
        total = g["riego_total_m3ha"]
        f["prev_n_ciclos"] = n.shift(1)
        f["prev_riego_total_m3ha"] = total.shift(1)
        f["prev_duracion_total_min"] = g["duracion_total_min"].shift(1)
        f["prev_inicio_primer_min"] = g["inicio_primer_min"].shift(1)
        f["prev_fin_ultimo_min"] = g["fin_ultimo_min"].shift(1)
        f["n_ciclos_d2"] = n.shift(2)
        f["n_ciclos_media7"] = n.shift(1).rolling(7, min_periods=3).mean()
        f["riego_total_m3ha_media3"] = total.shift(1).rolling(3, min_periods=2).mean()
        f["riego_total_m3ha_media7"] = total.shift(1).rolling(7, min_periods=3).mean()
        ultimo = pd.Series(idx, index=idx).where(n.notna()).ffill().shift(1)
        f["dias_desde_ultimo_riego"] = (pd.Series(idx, index=idx) - ultimo).dt.days
        for nombre, valor in zip(CLAVES_TURNO, claves):
            f[nombre] = valor
        frames.append(f.reset_index())
    return pd.concat(frames, ignore_index=True)


def features_ciclo_previo(ciclos: pd.DataFrame, fecha_max: pd.Timestamp) -> pd.DataFrame:
    """Lo que hizo el mismo número de ciclo del mismo turno días anteriores."""
    claves = [*CLAVES_TURNO, "Ciclo"]
    frames = []
    for valores, g in ciclos.groupby(claves):
        idx = _rejilla(g["Fecha"].min(), max(g["Fecha"].max(), fecha_max))
        g = g.set_index("Fecha").reindex(idx)
        f = pd.DataFrame(index=idx)
        f["prev_ciclo_m3ha"] = g["riego_m3ha"].shift(1)
        f["prev_ciclo_inicio_min"] = g["inicio_min"].shift(1)
        f["prev_ciclo_duracion_min"] = g["duracion_min"].shift(1)
        f["ciclo_m3ha_media7"] = g["riego_m3ha"].shift(1).rolling(7, min_periods=2).mean()
        f["ciclo_inicio_media7"] = g["inicio_min"].shift(1).rolling(7, min_periods=2).mean()
        for nombre, valor in zip(claves, valores):
            f[nombre] = valor
        frames.append(f.reset_index())
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- #
# Ensamblado
# --------------------------------------------------------------------------- #
def features_calendario(claves: pd.DataFrame) -> pd.DataFrame:
    f = claves.copy()
    doy = f["Fecha"].dt.dayofyear
    f["mes"] = f["Fecha"].dt.month
    f["dia_semana"] = f["Fecha"].dt.dayofweek
    f["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    f["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    f["turno_num"] = pd.to_numeric(f["Turno"].str.extract(r"(\d+)$")[0], errors="coerce")
    return f


def construir_features_turno(
    claves: pd.DataFrame,
    turno_dia_hist: pd.DataFrame,
    ambiente: pd.DataFrame,
    incluir_meteo_dia: bool = False,
) -> pd.DataFrame:
    """Features turno-día para las ``claves`` (Fecha, Fundo, Modulo, Turno)."""
    claves = claves[CLAVES_TD].drop_duplicates().copy()
    claves["Fecha"] = pd.to_datetime(claves["Fecha"]).dt.normalize()
    fecha_max = claves["Fecha"].max()

    out = features_calendario(claves)
    amb = features_ambiente(ambiente, fecha_max, incluir_meteo_dia)
    out = out.merge(amb, on=["Fundo", "Fecha"], how="left", validate="many_to_one")
    rieg = features_riego_previo(turno_dia_hist, fecha_max)
    out = out.merge(rieg, on=CLAVES_TD, how="left", validate="one_to_one")
    return out.sort_values(CLAVES_TD).reset_index(drop=True)


def construir_features_ciclo(
    filas: pd.DataFrame, features_turno: pd.DataFrame, ciclos_hist: pd.DataFrame
) -> pd.DataFrame:
    """Features por ciclo: las del turno-día + número de ciclo + ciclo previo.

    ``filas`` debe traer ``CLAVES_TD`` + ``Ciclo`` + ``n_ciclos`` (al entrenar
    es el observado; al predecir, el que estimó el clasificador).
    """
    out = filas.merge(features_turno, on=CLAVES_TD, how="left", validate="many_to_one")
    out["ciclo_rel"] = np.where(
        out["n_ciclos"] > 1, (out["Ciclo"] - 1) / (out["n_ciclos"] - 1).clip(lower=1), 0.0
    )
    prev = features_ciclo_previo(ciclos_hist, out["Fecha"].max())
    out = out.merge(prev, on=[*CLAVES_TD, "Ciclo"], how="left", validate="many_to_one")
    return out


def columnas_features(features_turno: pd.DataFrame, usar_suelo_absoluto: bool = False) -> list[str]:
    """Columnas de entrada del modelo turno-día (sin claves).

    Los niveles absolutos de humedad del suelo quedan fuera por defecto: el
    sensor cambió de régimen entre temporadas (p. ej. a 45 cm la media pasa de
    ~20 % a ~28 %) y los modelos que los usan no generalizan. Se conservan los
    cambios en 24 h, que son relativos y robustos a recalibraciones.
    """
    columnas = [c for c in features_turno.columns if c not in CLAVES_TD or c in CATEGORICAS]
    if not usar_suelo_absoluto:
        columnas = [c for c in columnas if c not in suelo_absoluto(columnas)]
    return columnas


def suelo_absoluto(columnas: list[str]) -> list[str]:
    return [c for c in columnas if c.endswith("_cierre_d1") or c == "dist_linea_estres_d1"]


FEATURES_SOLO_CICLO = [
    "Ciclo", "n_ciclos", "ciclo_rel", "prev_ciclo_m3ha", "prev_ciclo_inicio_min",
    "prev_ciclo_duracion_min", "ciclo_m3ha_media7", "ciclo_inicio_media7",
]

LIMITE_INICIO = (0.0, MINUTOS_DIA - 1.0)
