"""Armado del plan de riego a partir de los modelos entrenados.

Para cada turno-día:

1. El clasificador estima ``n_ciclos``.
2. Para cada ciclo k = 1..n_ciclos los regresores estiman ``riego_m3ha`` y
   ``inicio_min``.
3. La duración se deriva del volumen con el caudal propio de cada turno
   (``min_por_m3ha``, mediana histórica de duración / m3·ha⁻¹). Así volumen,
   duración y hora de fin son siempre coherentes entre sí.
4. Se ordenan los ciclos por hora de inicio y se corrigen solapamientos:
   un ciclo no empieza antes de que termine el anterior (+ pausa mínima).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from riego_ml.dataset.features import construir_features_ciclo
from riego_ml.dataset.limpieza import CLAVES_TD
from riego_ml.utils.tiempo import MINUTOS_DIA, minutes_to_hhmm


@dataclass
class PlanRiego:
    modelo_n_ciclos: Any
    modelo_m3ha: Any
    modelo_inicio: Any
    features_turno: list[str]
    features_ciclo: list[str]
    max_ciclos: int
    min_por_m3ha: dict[str, float]
    area_ha: dict[str, float]
    rango_m3ha: tuple[float, float]
    pausa_min: float = 0.0
    elegidos: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    def predecir_n_ciclos(self, features_turno: pd.DataFrame) -> np.ndarray:
        pred = self.modelo_n_ciclos.predict(features_turno[self.features_turno])
        return np.clip(np.rint(np.asarray(pred, dtype=float)), 1, self.max_ciclos).astype(int)

    def predecir_ciclos(self, filas_ciclo: pd.DataFrame) -> pd.DataFrame:
        """Predice m3/ha e inicio para filas con features de ciclo ya construidas."""
        out = filas_ciclo.copy()
        X = out[self.features_ciclo]
        out["riego_m3ha"] = np.clip(self.modelo_m3ha.predict(X), *self.rango_m3ha)
        out["inicio_min"] = np.clip(self.modelo_inicio.predict(X), 0.0, MINUTOS_DIA - 1.0)
        return out

    def duracion(self, turnos: pd.Series, m3ha: pd.Series) -> np.ndarray:
        ratio = turnos.map(self.min_por_m3ha).fillna(np.nanmedian(list(self.min_por_m3ha.values())))
        return np.asarray(m3ha, dtype=float) * ratio.to_numpy(dtype=float)

    def predecir(self, features_turno: pd.DataFrame, ciclos_hist: pd.DataFrame) -> pd.DataFrame:
        """Plan en formato largo: 1 fila por ciclo programado."""
        extra = [c for c in self.features_turno if c not in CLAVES_TD]
        base = features_turno[[*CLAVES_TD, *extra]].reset_index(drop=True)
        n = self.predecir_n_ciclos(base)
        filas = base.loc[base.index.repeat(n), CLAVES_TD].reset_index(drop=True)
        filas["n_ciclos"] = np.repeat(n, n)
        filas["Ciclo"] = np.concatenate([np.arange(1, k + 1) for k in n])
        filas = construir_features_ciclo(filas, base, ciclos_hist)
        plan = self.predecir_ciclos(filas)
        plan["duracion_min"] = self.duracion(plan["Turno"], plan["riego_m3ha"])
        return self.armar_horario(plan)

    def armar_horario(self, plan: pd.DataFrame) -> pd.DataFrame:
        plan = plan.sort_values([*CLAVES_TD, "inicio_min"], kind="stable").reset_index(drop=True)
        plan["Ciclo"] = plan.groupby(CLAVES_TD).cumcount() + 1
        inicios = plan["inicio_min"].to_numpy(dtype=float).copy()
        duraciones = plan["duracion_min"].to_numpy(dtype=float)
        fin_previo = -np.inf
        claves_previas = None
        for i, claves in enumerate(plan[CLAVES_TD].itertuples(index=False, name=None)):
            if claves != claves_previas:
                fin_previo, claves_previas = -np.inf, claves
            inicios[i] = max(inicios[i], fin_previo + self.pausa_min)
            fin_previo = inicios[i] + duraciones[i]
        plan["inicio_min"] = inicios
        plan["fin_min"] = inicios + duraciones
        plan["hora_inicio"] = plan["inicio_min"].map(minutes_to_hhmm)
        plan["hora_fin"] = plan["fin_min"].map(minutes_to_hhmm)
        plan["fin_dia_siguiente"] = (plan["fin_min"] >= MINUTOS_DIA).astype(int)
        plan["riego_m3"] = plan["riego_m3ha"] * plan["Turno"].map(self.area_ha)
        columnas = [
            *CLAVES_TD, "n_ciclos", "Ciclo", "riego_m3ha", "riego_m3", "duracion_min",
            "hora_inicio", "hora_fin", "fin_dia_siguiente", "inicio_min", "fin_min",
        ]
        return plan[columnas].round(
            {"riego_m3ha": 2, "riego_m3": 1, "duracion_min": 1, "inicio_min": 1, "fin_min": 1}
        )


def plan_ancho(plan: pd.DataFrame, max_ciclos: int) -> pd.DataFrame:
    """1 fila por turno-día: n_ciclos y, por cada ciclo, m3/ha, duración, inicio y fin."""
    filas = []
    for claves, g in plan.groupby(CLAVES_TD, sort=True):
        fila = dict(zip(CLAVES_TD, claves))
        fila["n_ciclos"] = int(g["n_ciclos"].iloc[0])
        fila["riego_total_m3ha"] = round(float(g["riego_m3ha"].sum()), 2)
        fila["duracion_total_min"] = round(float(g["duracion_min"].sum()), 1)
        for k in range(1, max_ciclos + 1):
            c = g[g["Ciclo"] == k]
            vacio = c.empty
            fila[f"ciclo{k}_m3ha"] = np.nan if vacio else c["riego_m3ha"].iloc[0]
            fila[f"ciclo{k}_duracion_min"] = np.nan if vacio else c["duracion_min"].iloc[0]
            fila[f"ciclo{k}_hora_inicio"] = "" if vacio else c["hora_inicio"].iloc[0]
            fila[f"ciclo{k}_hora_fin"] = "" if vacio else c["hora_fin"].iloc[0]
        filas.append(fila)
    return pd.DataFrame(filas)
