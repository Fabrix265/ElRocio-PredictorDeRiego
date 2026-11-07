"""Predicción del plan de riego para una o varias fechas.

Para varias fechas seguidas la predicción es recursiva: el plan estimado para
el día D se agrega al historial como "riego de ayer" del día D+1 (en
producción normalmente se planifica solo el día siguiente).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import joblib
import pandas as pd

from riego_ml.config import Config
from riego_ml.dataset.limpieza import tabla_turno_dia
from riego_ml.dataset.preparar import Historial, features_para_fechas
from riego_ml.modeling.entrenamiento import NOMBRE_BUNDLE
from riego_ml.modeling.planificador import PlanRiego


def cargar_plan(config: Config, ruta: str | Path | None = None) -> PlanRiego:
    if ruta:
        ruta = Path(ruta)
        if ruta.is_dir():
            ruta = ruta / NOMBRE_BUNDLE
    else:
        ruta = config.rutas.modelos_dir / "plan_riego" / "actual" / NOMBRE_BUNDLE
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el modelo {ruta}. Ejecuta primero entrenar.py.")
    plan = joblib.load(ruta)
    if not isinstance(plan, PlanRiego):
        raise TypeError(f"{ruta} no contiene un PlanRiego.")
    return plan


def planificar(plan: PlanRiego, historial: Historial, fechas: list[pd.Timestamp], config: Config) -> pd.DataFrame:
    fechas = sorted(pd.to_datetime(fechas).normalize())
    resultados = []
    for fecha in fechas:
        features = features_para_fechas(historial, [fecha], config)
        dia = plan.predecir(features, historial.ciclos)
        resultados.append(dia)
        historial = _agregar_al_historial(historial, dia)
    return pd.concat(resultados, ignore_index=True)


def _agregar_al_historial(historial: Historial, plan_dia: pd.DataFrame) -> Historial:
    nuevos = plan_dia.copy()
    nuevos["area_ha"] = nuevos["riego_m3"] / nuevos["riego_m3ha"]
    fechas = set(nuevos["Fecha"])
    ciclos = historial.ciclos[~historial.ciclos["Fecha"].isin(fechas)]
    ciclos = pd.concat([ciclos, nuevos[[c for c in ciclos.columns if c in nuevos.columns]]], ignore_index=True)
    return replace(historial, ciclos=ciclos, turno_dia=tabla_turno_dia(ciclos))
