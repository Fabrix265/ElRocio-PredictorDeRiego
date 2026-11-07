"""Split temporal train -> validación -> test con días de separación (gap).

Se divide por FECHAS (no por filas) para que un mismo día nunca quede en dos
conjuntos, y se dejan ``gap_dias`` sin usar entre bloques para que los rezagos
(promedios de 7 días, día anterior) no conecten train con validación/test.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class CortesTemporales:
    fin_train: pd.Timestamp
    inicio_validacion: pd.Timestamp
    fin_validacion: pd.Timestamp
    inicio_test: pd.Timestamp

    def asignar(self, fechas: pd.Series) -> pd.Series:
        fechas = pd.to_datetime(fechas)
        conjunto = pd.Series("gap", index=fechas.index, dtype="object")
        conjunto[fechas <= self.fin_train] = "train"
        conjunto[(fechas >= self.inicio_validacion) & (fechas <= self.fin_validacion)] = "validacion"
        conjunto[fechas >= self.inicio_test] = "test"
        return conjunto

    def to_dict(self) -> dict[str, str]:
        return {k: f"{v:%Y-%m-%d}" for k, v in self.__dict__.items()}


def cortes_temporales(fechas: pd.Series, test: float, validacion: float, gap_dias: int) -> CortesTemporales:
    unicas = np.sort(pd.to_datetime(fechas).dt.normalize().unique())
    total = len(unicas)
    if total < 30:
        raise ValueError("Se necesitan al menos 30 fechas para el split temporal.")
    gap = pd.Timedelta(days=gap_dias)
    inicio_test = pd.Timestamp(unicas[int(total * (1 - test))])
    fin_validacion = inicio_test - gap - pd.Timedelta(days=1)
    n_val = int(total * validacion)
    candidatas = unicas[unicas <= fin_validacion]
    inicio_validacion = pd.Timestamp(candidatas[max(0, len(candidatas) - n_val)])
    fin_train = inicio_validacion - gap - pd.Timedelta(days=1)
    if fin_train <= pd.Timestamp(unicas[0]):
        raise ValueError("El split dejó el train vacío: reduce test, validación o gap.")
    return CortesTemporales(fin_train, inicio_validacion, fin_validacion, inicio_test)


def folds_temporales(fechas: pd.Series, n_folds: int, gap_dias: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """Folds de ventana creciente por fecha (para la búsqueda de hiperparámetros)."""
    fechas = pd.to_datetime(fechas).reset_index(drop=True)
    unicas = np.sort(fechas.unique())
    tam = len(unicas) // (n_folds + 1)
    folds = []
    for k in range(1, n_folds + 1):
        ini_val = pd.Timestamp(unicas[k * tam])
        fin_val = pd.Timestamp(unicas[min(len(unicas) - 1, (k + 1) * tam - 1)])
        train = np.flatnonzero(fechas < ini_val - pd.Timedelta(days=gap_dias))
        val = np.flatnonzero((fechas >= ini_val) & (fechas <= fin_val))
        if len(train) and len(val):
            folds.append((train, val))
    return folds
