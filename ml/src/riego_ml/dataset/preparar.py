"""Paso 2 - Limpia el dataset unido y arma las tablas listas para entrenar.

* ``turno_dia``: 1 fila por turno-día -> target ``n_ciclos``.
* ``ciclos``: 1 fila por ciclo -> targets ``riego_m3ha`` e ``inicio_min``
  (la duración y la hora de fin se derivan; ver ``modeling.planificador``).
* ``columnas``: qué columnas son features y cuáles targets (evita fugas).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from riego_ml.config import Config
from riego_ml.dataset.features import (
    CATEGORICAS,
    FEATURES_SOLO_CICLO,
    columnas_features,
    construir_features_ciclo,
    construir_features_turno,
)
from riego_ml.dataset.limpieza import CLAVES_TD, limpiar_ciclos, tabla_turno_dia

TARGET_TURNO = "n_ciclos"
TARGETS_CICLO = ["riego_m3ha", "inicio_min"]
OBSERVADOS_TURNO = [
    "n_ciclos", "riego_total_m3ha", "riego_total_m3", "duracion_total_min",
    "inicio_primer_min", "fin_ultimo_min", "area_ha", "dia_incompleto",
]
OBSERVADOS_CICLO = [
    "riego_m3ha", "riego_m3", "inicio_min", "duracion_min", "fin_min",
    "hora_inicio", "hora_fin", "fin_dia_siguiente", "area_ha", "solapado",
]


@dataclass
class Historial:
    """Ciclos limpios + tabla turno-día + ambiente diario (base para features)."""

    ciclos: pd.DataFrame
    turno_dia: pd.DataFrame
    ambiente: pd.DataFrame
    descartados: pd.DataFrame
    diagnostico: dict = field(default_factory=dict)


@dataclass
class DatasetEntrenamiento:
    turno_dia: pd.DataFrame
    ciclos: pd.DataFrame
    columnas: dict
    diagnostico: dict


def cargar_historial(config: Config) -> Historial:
    carpeta = config.rutas.interim_dir
    rutas = [carpeta / "riego_unido.csv", carpeta / "ambiente_diario.csv"]
    faltan = [str(r) for r in rutas if not r.exists()]
    if faltan:
        raise FileNotFoundError(f"Faltan salidas del paso 1 (unir_datos.py): {faltan}")
    riego = pd.read_csv(rutas[0], parse_dates=["Fecha"])
    ambiente = pd.read_csv(rutas[1], parse_dates=["Fecha"])
    prep = config.preparacion
    ciclos, descartados, diag = limpiar_ciclos(riego, prep.min_duracion_min, prep.min_riego_m3ha)
    return Historial(ciclos, tabla_turno_dia(ciclos), ambiente, descartados, diag)


def _filtrar_fechas(df: pd.DataFrame, desde: str | None, hasta: str | None) -> pd.DataFrame:
    if desde:
        df = df[df["Fecha"] >= pd.Timestamp(desde)]
    if hasta:
        df = df[df["Fecha"] <= pd.Timestamp(hasta)]
    return df.reset_index(drop=True)


def preparar_entrenamiento(historial: Historial, config: Config) -> DatasetEntrenamiento:
    prep = config.preparacion
    td_obs = historial.turno_dia
    feats_turno = construir_features_turno(
        td_obs[CLAVES_TD], td_obs, historial.ambiente, prep.incluir_meteo_dia
    )
    features_turno = columnas_features(feats_turno)

    turno_dia = td_obs.merge(feats_turno, on=CLAVES_TD, how="left", validate="one_to_one")
    turno_dia = _filtrar_fechas(turno_dia, prep.desde, prep.hasta)

    ciclos_obs = historial.ciclos[[*CLAVES_TD, "Ciclo", "n_ciclos", *OBSERVADOS_CICLO]]
    ciclos = construir_features_ciclo(ciclos_obs, feats_turno, historial.ciclos)
    ciclos = ciclos.merge(
        td_obs[[*CLAVES_TD, "dia_incompleto"]], on=CLAVES_TD, how="left", validate="many_to_one"
    )
    ciclos = _filtrar_fechas(ciclos, prep.desde, prep.hasta)
    features_ciclo = [*features_turno, *FEATURES_SOLO_CICLO]

    columnas = {
        "claves": CLAVES_TD,
        "categoricas": CATEGORICAS,
        "features_turno": features_turno,
        "features_ciclo": features_ciclo,
        "target_turno": TARGET_TURNO,
        "targets_ciclo": TARGETS_CICLO,
        "observados_turno": OBSERVADOS_TURNO,
        "observados_ciclo": OBSERVADOS_CICLO,
        "derivados": ["duracion_min", "fin_min", "hora_inicio", "hora_fin"],
    }
    diag = dict(historial.diagnostico)
    diag.update(_diagnostico(turno_dia, ciclos, features_turno))
    solo_features_turno = [c for c in features_turno if c not in CLAVES_TD]
    solo_features_ciclo = [c for c in FEATURES_SOLO_CICLO if c not in ("Ciclo", "n_ciclos")]
    return DatasetEntrenamiento(
        turno_dia[[*CLAVES_TD, *OBSERVADOS_TURNO, *solo_features_turno]],
        ciclos[[*CLAVES_TD, "Ciclo", "n_ciclos", *OBSERVADOS_CICLO, "dia_incompleto",
                *solo_features_turno, *solo_features_ciclo]],
        columnas,
        diag,
    )


def features_para_fechas(historial: Historial, fechas: list[pd.Timestamp], config: Config) -> pd.DataFrame:
    """Features turno-día para planificar las ``fechas`` (todos los turnos conocidos)."""
    turnos = historial.turno_dia[["Fundo", "Modulo", "Turno"]].drop_duplicates()
    claves = turnos.merge(pd.DataFrame({"Fecha": pd.to_datetime(fechas).normalize()}), how="cross")
    return construir_features_turno(
        claves[CLAVES_TD], historial.turno_dia, historial.ambiente,
        config.preparacion.incluir_meteo_dia,
    )


def _diagnostico(turno_dia: pd.DataFrame, ciclos: pd.DataFrame, features: list[str]) -> dict:
    diag = {
        "Entrenamiento: turno-días": len(turno_dia),
        "Entrenamiento: ciclos": len(ciclos),
        "Entrenamiento: rango de fechas": f"{turno_dia['Fecha'].min():%Y-%m-%d} a {turno_dia['Fecha'].max():%Y-%m-%d}",
        "Entrenamiento: turno-días en días incompletos": int(turno_dia["dia_incompleto"].sum()),
        "Entrenamiento: n features turno-día": len(features),
        "Entrenamiento: distribución n_ciclos": turno_dia["n_ciclos"].value_counts().sort_index().to_dict(),
    }
    for columna in [
        "ETo_mm_d1", "hum_45cm_cierre_d1", "hum_zona_radicular_cierre_d1",
        "mds_contraccion_um_d1", "prev_n_ciclos",
    ]:
        if columna in turno_dia:
            diag[f"Cobertura {columna}"] = f"{turno_dia[columna].notna().mean() * 100:.1f}%"
    return diag


def guardar(dataset: DatasetEntrenamiento, carpeta: Path) -> None:
    import json

    carpeta.mkdir(parents=True, exist_ok=True)
    dataset.turno_dia.to_csv(carpeta / "turno_dia.csv", index=False)
    dataset.ciclos.to_csv(carpeta / "ciclos.csv", index=False)
    (carpeta / "columnas.json").write_text(
        json.dumps(dataset.columnas, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def cargar_dataset(carpeta: Path) -> DatasetEntrenamiento:
    import json

    rutas = [carpeta / "turno_dia.csv", carpeta / "ciclos.csv", carpeta / "columnas.json"]
    faltan = [str(r) for r in rutas if not r.exists()]
    if faltan:
        raise FileNotFoundError(f"Faltan salidas del paso 2 (preparar_dataset.py): {faltan}")
    turno_dia = pd.read_csv(rutas[0], parse_dates=["Fecha"])
    ciclos = pd.read_csv(rutas[1], parse_dates=["Fecha"])
    columnas = json.loads(rutas[2].read_text(encoding="utf-8"))
    return DatasetEntrenamiento(turno_dia, ciclos, columnas, {})
