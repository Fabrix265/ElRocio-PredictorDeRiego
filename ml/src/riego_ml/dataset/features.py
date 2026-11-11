"""Features del plan de riego, todas conocidas a las 00:00 del día a planificar.

Regla anti-fuga: para predecir el día D solo se usa información hasta el día
D-1 (meteo y planta del día anterior, suelo al cierre del día anterior, riego
de días anteriores). La única excepción son los feriados, que se conocen de
antemano. La misma función se usa para entrenar y para predecir, así no hay
diferencias entre ambos momentos.

Grupos de features
------------------
* Base: calendario, meteo de ayer y ventanas, cambios del suelo en 24 h,
  planta de ayer, riego previo del turno y del mismo número de ciclo.
* Extendidas (``preparacion.features_extendidas``):
  - Rotación de turnos: en qué orden y a qué hora arrancó cada turno ayer,
    cuánto después del arranque del módulo y del turno anterior.
  - Patrón semanal: lo que se hizo hace 7 días.
  - Estabilidad y tendencia del número de ciclos.
  - Balance hídrico 7 días: demanda (ETo) vs. riego aplicado.
  - Calor de ayer, tendencia de la ETo, anomalía del MDS, respuesta del
    suelo al riego, NDVI y feriados.

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
M3HA_POR_MM = 10.0  # 1 mm de lámina = 10 m3/ha

FEATURES_EXTENDIDAS_TURNO = [
    # rotación de turnos
    "orden_arranque_d1", "inicio_modulo_d1", "desfase_modulo_d1", "desfase_turno_previo_d1",
    # patrón semanal, estabilidad y tendencia
    "inicio_primer_d7", "n_ciclos_d7", "dias_desde_cambio_n", "cambios_n_14d", "n_ciclos_tendencia",
    # agua: balance y demanda
    "balance_hidrico_7d", "reposicion_7d", "ETo_media14", "ETo_tendencia",
    # clima, planta, suelo, vigor y calendario
    "horas_T30_d1", "mds_anom7", "crecimiento_acum7", "resp_hum_45cm_d1", "resp_hum_60cm_d1",
    "ndvi_ultimo", "ndvi_cambio_30d", "es_feriado", "vispera_feriado", "post_feriado",
]
FEATURES_EXTENDIDAS_CICLO = [
    "ciclo_m3ha_d7", "ciclo_inicio_d7", "ciclo_m3ha_mediana7", "prev_ciclo_desfase_min",
]


def _rejilla(fechas_min: pd.Timestamp, fechas_max: pd.Timestamp) -> pd.DatetimeIndex:
    return pd.date_range(fechas_min, fechas_max, freq="D", name="Fecha")


def _col(df: pd.DataFrame, nombre: str) -> pd.Series:
    """Columna o serie vacía (tolera ambientes viejos sin las columnas nuevas)."""
    return df[nombre] if nombre in df else pd.Series(np.nan, index=df.index)


# --------------------------------------------------------------------------- #
# Ambiente (meteo + suelo + planta + NDVI)
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
        f["ETo_media14"] = eto.rolling(14, min_periods=7).mean()
        f["ETo_tendencia"] = f["ETo_media3"] - f["ETo_media14"]
        f["T_max_media3"] = a["T_max"].shift(1).rolling(3, min_periods=2).mean()
        f["Lluvia_acum7"] = a["Lluvia_mm"].shift(1).rolling(7, min_periods=4).sum()
        f["horas_T30_d1"] = _col(a, "horas_T30").shift(1)

        for c in SUELO_D1:
            f[f"{c}_cierre_d1"] = a[f"{c}_cierre"].shift(1)
        f["dist_linea_estres_d1"] = (
            a["hum_zona_radicular_cierre"] - a["hum_linea_estres_cierre"]
        ).shift(1)
        f["d_hum_zona_24h"] = a["hum_zona_radicular_cierre"].shift(1) - a["hum_zona_radicular_cierre"].shift(2)
        f["d_hum_45cm_24h"] = a["hum_45cm_cierre"].shift(1) - a["hum_45cm_cierre"].shift(2)
        f["resp_hum_45cm_d1"] = _col(a, "hum_45cm_rango").shift(1)
        f["resp_hum_60cm_d1"] = _col(a, "hum_60cm_rango").shift(1)

        for c in PLANTA_D1:
            f[f"{c}_d1"] = a[c].shift(1)
        mds = a["mds_contraccion_um"].shift(1)
        f["mds_media3"] = mds.rolling(3, min_periods=2).mean()
        f["mds_anom7"] = mds - mds.rolling(7, min_periods=4).mean()
        f["crecimiento_acum7"] = a["crecimiento_tronco_um"].shift(1).rolling(7, min_periods=4).sum()

        ndvi = _col(a, "ndvi_medio").ffill(limit=45).shift(1)
        f["ndvi_ultimo"] = ndvi
        f["ndvi_cambio_30d"] = ndvi - ndvi.shift(30)

        if incluir_meteo_dia:
            for c in METEO_D1:
                f[f"{c}_dia"] = a[c]

        f["Fundo"] = fundo
        frames.append(f.reset_index())
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- #
# Historial de riego del mismo turno
# --------------------------------------------------------------------------- #
def _rotacion(turno_dia: pd.DataFrame) -> pd.DataFrame:
    """Orden y desfase de arranque de cada turno dentro de su módulo cada día."""
    td = turno_dia.copy()
    grupo = td.groupby(["Fecha", "Fundo", "Modulo"])["inicio_primer_min"]
    td["orden_arranque"] = grupo.rank(method="first")
    td["inicio_modulo"] = grupo.transform("min")
    td["desfase_modulo"] = td["inicio_primer_min"] - td["inicio_modulo"]
    ordenado = td.sort_values(["Fecha", "Fundo", "Modulo", "inicio_primer_min"])
    previo = ordenado.groupby(["Fecha", "Fundo", "Modulo"])["inicio_primer_min"].shift(1)
    td["desfase_turno_previo"] = (ordenado["inicio_primer_min"] - previo).reindex(td.index)
    return td


def features_riego_previo(turno_dia: pd.DataFrame, fecha_max: pd.Timestamp) -> pd.DataFrame:
    """Rezagos autorregresivos del mismo turno (lo regado días anteriores)."""
    frames = []
    for claves, g in _rotacion(turno_dia).groupby(CLAVES_TURNO):
        idx = _rejilla(g["Fecha"].min(), max(g["Fecha"].max(), fecha_max))
        g = g.set_index("Fecha").reindex(idx)
        f = pd.DataFrame(index=idx)
        n = g["n_ciclos"]
        total = g["riego_total_m3ha"]
        inicio = g["inicio_primer_min"]
        f["prev_n_ciclos"] = n.shift(1)
        f["prev_riego_total_m3ha"] = total.shift(1)
        f["prev_duracion_total_min"] = g["duracion_total_min"].shift(1)
        f["prev_inicio_primer_min"] = inicio.shift(1)
        f["prev_fin_ultimo_min"] = g["fin_ultimo_min"].shift(1)
        f["n_ciclos_d2"] = n.shift(2)
        f["n_ciclos_media7"] = n.shift(1).rolling(7, min_periods=3).mean()
        f["riego_total_m3ha_media3"] = total.shift(1).rolling(3, min_periods=2).mean()
        f["riego_total_m3ha_media7"] = total.shift(1).rolling(7, min_periods=3).mean()
        fechas = pd.Series(idx, index=idx)
        ultimo = fechas.where(n.notna()).ffill().shift(1)
        f["dias_desde_ultimo_riego"] = (fechas - ultimo).dt.days

        # Rotación de turnos (ayer) y patrón semanal (hace 7 días)
        f["orden_arranque_d1"] = g["orden_arranque"].shift(1)
        f["inicio_modulo_d1"] = g["inicio_modulo"].shift(1)
        f["desfase_modulo_d1"] = g["desfase_modulo"].shift(1)
        f["desfase_turno_previo_d1"] = g["desfase_turno_previo"].shift(1)
        f["inicio_primer_d7"] = inicio.shift(7)
        f["n_ciclos_d7"] = n.shift(7)

        # Estabilidad y tendencia del número de ciclos
        cambio = (n != n.shift(1)) & n.notna() & n.shift(1).notna()
        ultimo_cambio = fechas.where(cambio).ffill().shift(1)
        f["dias_desde_cambio_n"] = (fechas - ultimo_cambio).dt.days
        f["cambios_n_14d"] = cambio.astype(float).shift(1).rolling(14, min_periods=7).sum()
        f["n_ciclos_tendencia"] = (
            n.shift(1).rolling(3, min_periods=2).mean() - n.shift(1).rolling(14, min_periods=7).mean()
        )
        f["_riego_acum7"] = total.shift(1).rolling(7, min_periods=5).sum()
        # Minutos por cada m3/ha del turno en los últimos 30 días (refleja el caudal
        # actual de la válvula, que cambia con el tiempo). Se usa para derivar la duración.
        ratio = (g["duracion_total_min"] / total.where(total > 0))
        f["min_por_m3ha_30d"] = ratio.shift(1).rolling(30, min_periods=5).median()

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
        m3ha = g["riego_m3ha"]
        inicio = g["inicio_min"]
        f["prev_ciclo_m3ha"] = m3ha.shift(1)
        f["prev_ciclo_inicio_min"] = inicio.shift(1)
        f["prev_ciclo_duracion_min"] = g["duracion_min"].shift(1)
        f["ciclo_m3ha_media7"] = m3ha.shift(1).rolling(7, min_periods=2).mean()
        f["ciclo_inicio_media7"] = inicio.shift(1).rolling(7, min_periods=2).mean()
        f["ciclo_m3ha_d7"] = m3ha.shift(7)
        f["ciclo_inicio_d7"] = inicio.shift(7)
        # Dosis habitual: la mediana es robusta a un día atípico.
        f["ciclo_m3ha_mediana7"] = m3ha.shift(1).rolling(7, min_periods=2).median()
        for nombre, valor in zip(claves, valores):
            f[nombre] = valor
        frames.append(f.reset_index())
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------- #
# Ensamblado
# --------------------------------------------------------------------------- #
def _feriados(fechas: pd.Series) -> pd.DataFrame:
    try:
        import holidays

        anios = range(int(fechas.dt.year.min()) - 1, int(fechas.dt.year.max()) + 2)
        dias = {pd.Timestamp(d) for d in holidays.Peru(years=anios)}
    except ImportError:  # sin la librería, las columnas quedan en 0
        dias = set()
    return pd.DataFrame({
        "es_feriado": fechas.isin(dias).astype(int),
        "vispera_feriado": (fechas + pd.Timedelta(days=1)).isin(dias).astype(int),
        "post_feriado": (fechas - pd.Timedelta(days=1)).isin(dias).astype(int),
    }, index=fechas.index)


def features_calendario(claves: pd.DataFrame) -> pd.DataFrame:
    f = claves.copy()
    doy = f["Fecha"].dt.dayofyear
    f["mes"] = f["Fecha"].dt.month
    f["dia_semana"] = f["Fecha"].dt.dayofweek
    f["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    f["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    f["turno_num"] = pd.to_numeric(f["Turno"].str.extract(r"(\d+)$")[0], errors="coerce")
    return pd.concat([f, _feriados(f["Fecha"])], axis=1)


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

    # Balance hídrico de los últimos 7 días: demanda (ETo) vs. riego aplicado.
    demanda = out["ETo_media7"] * 7 * M3HA_POR_MM
    out["balance_hidrico_7d"] = demanda - out["_riego_acum7"]
    out["reposicion_7d"] = out["_riego_acum7"] / demanda.where(demanda > 0)
    out = out.drop(columns=["_riego_acum7"])
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
    if "prev_inicio_primer_min" in out:
        out["prev_ciclo_desfase_min"] = out["prev_ciclo_inicio_min"] - out["prev_inicio_primer_min"]
    return out


def columnas_features(
    features_turno: pd.DataFrame, usar_suelo_absoluto: bool = False, extendidas: bool = True
) -> list[str]:
    """Columnas de entrada del modelo turno-día (sin claves).

    Los niveles absolutos de humedad del suelo quedan fuera por defecto: el
    sensor cambió de régimen entre temporadas (p. ej. a 45 cm la media pasa de
    ~20 % a ~28 %) y los modelos que los usan no generalizan. Se conservan los
    cambios en 24 h y la respuesta diaria, que son relativos.
    """
    columnas = [c for c in features_turno.columns if c not in CLAVES_TD or c in CATEGORICAS]
    if not usar_suelo_absoluto:
        columnas = [c for c in columnas if c not in suelo_absoluto(columnas)]
    if not extendidas:
        columnas = [c for c in columnas if c not in FEATURES_EXTENDIDAS_TURNO]
    return columnas


def suelo_absoluto(columnas: list[str]) -> list[str]:
    return [c for c in columnas if c.endswith("_cierre_d1") or c == "dist_linea_estres_d1"]


FEATURES_SOLO_CICLO_BASE = [
    "Ciclo", "n_ciclos", "ciclo_rel", "prev_ciclo_m3ha", "prev_ciclo_inicio_min",
    "prev_ciclo_duracion_min", "ciclo_m3ha_media7", "ciclo_inicio_media7",
]


def features_solo_ciclo(extendidas: bool = True) -> list[str]:
    return [*FEATURES_SOLO_CICLO_BASE, *(FEATURES_EXTENDIDAS_CICLO if extendidas else [])]


# Compatibilidad: lista completa por defecto
FEATURES_SOLO_CICLO = features_solo_ciclo(True)

LIMITE_INICIO = (0.0, MINUTOS_DIA - 1.0)
