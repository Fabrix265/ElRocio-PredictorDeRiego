"""Adaptador: el total de m³/ha de cada turno-día sale de un modelo directo (Random Forest).

``PlanTotalTurno`` envuelve un ``PlanRiego`` ya entrenado **sin cambiar su lógica**:

1. Igual que ``PlanRiego.predecir``: n° de ciclos, m³/ha e inicio de cada ciclo.
2. Nuevo: un modelo directo estima el total de m³/ha del turno-día y los ciclos se escalan para
   sumar ese total (se conservan el n° de ciclos, el reparto relativo y las horas de inicio).
3. Igual que ``PlanRiego.predecir``: duración con el caudal del turno y horario sin solapes.

Motivo: con riego por pulsos solo se usa el total por turno, y el total "n° de ciclos × m³/ha por
ciclo" se infla cuando cambia el tamaño de los ciclos en campo (noviembre 2026).

Al ser subclase de ``PlanRiego``, el backend lo carga y lo usa sin cambios. Las alternativas con
otro n° de ciclos (``predecir_ciclos`` forzando n) siguen saliendo del modelo por ciclo original.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

import numpy as np
import pandas as pd

from riego_ml.dataset.features import construir_features_ciclo
from riego_ml.dataset.limpieza import CLAVES_TD, tabla_turno_dia
from riego_ml.modeling.planificador import PlanRiego

COLUMNAS_REFERENCIA = ("ref_ayer", "ref_media3", "ref_media7", "ref_mediana7")
RELLENO_NAN = -999.0  # el Random Forest de sklearn se entrenó con los faltantes en -999


def referencias_total(turno_dia: pd.DataFrame, fechas_extra: list[pd.Timestamp] | tuple = ()) -> pd.DataFrame:
    """Total del mismo turno en días anteriores: ayer, media de 3 y 7 días y mediana de 7 días.

    Solo usa días anteriores (``shift(1)`` sobre el calendario diario): un día sin registro cuenta
    como faltante, no como cero. ``fechas_extra``: días a planificar que aún no están en el historial.
    """
    salida = []
    for (fundo, modulo, turno), g in turno_dia.groupby(["Fundo", "Modulo", "Turno"]):
        s = g.groupby("Fecha")["riego_total_m3ha"].sum()
        idx = pd.date_range(s.index.min(), max([s.index.max(), *fechas_extra]), freq="D")
        p = s.reindex(idx).shift(1)
        salida.append(pd.DataFrame({
            "Fecha": idx, "Fundo": fundo, "Modulo": modulo, "Turno": turno,
            "ref_ayer": p.to_numpy(),
            "ref_media3": p.rolling(3, min_periods=2).mean().to_numpy(),
            "ref_media7": p.rolling(7, min_periods=3).mean().to_numpy(),
            "ref_mediana7": p.rolling(7, min_periods=3).median().to_numpy(),
        }))
    if not salida:
        return pd.DataFrame(columns=[*CLAVES_TD, *COLUMNAS_REFERENCIA])
    return pd.concat(salida, ignore_index=True)


def agregar_referencias(features_turno: pd.DataFrame, turno_dia: pd.DataFrame) -> pd.DataFrame:
    """``features_turno`` con las columnas ``ref_*`` (calculadas con ``turno_dia``)."""
    sin_ref = features_turno.drop(columns=[c for c in COLUMNAS_REFERENCIA if c in features_turno])
    extra = sorted(set(pd.to_datetime(sin_ref["Fecha"])) - set(turno_dia["Fecha"]))
    refs = referencias_total(turno_dia, extra)
    return sin_ref.merge(refs, on=CLAVES_TD, how="left")


@dataclass
class PlanTotalTurno(PlanRiego):
    modelo_total: Any = None
    columnas_total: list[str] = field(default_factory=list)

    @classmethod
    def desde_plan(cls, plan: PlanRiego, modelo_total: Any, columnas_total: list[str],
                   metadata: dict[str, Any] | None = None) -> "PlanTotalTurno":
        campos = {f.name: getattr(plan, f.name) for f in fields(PlanRiego)}
        if metadata is not None:
            campos["metadata"] = metadata
        return cls(**campos, modelo_total=modelo_total, columnas_total=list(columnas_total))

    # ------------------------------------------------------------------ #
    def columnas_turno(self) -> list[str]:
        """Las del plan original + las del modelo del total (sin las ``ref_*``, que se calculan aquí)."""
        extra = [c for c in self.columnas_total if c not in COLUMNAS_REFERENCIA]
        return list(dict.fromkeys([*super().columnas_turno(), *extra]))

    def predecir_total(self, features_turno: pd.DataFrame, ciclos_hist: pd.DataFrame) -> pd.DataFrame:
        """Total de m³/ha por turno-día (``CLAVES_TD`` + ``total_m3ha``)."""
        filas = agregar_referencias(features_turno, tabla_turno_dia(ciclos_hist))
        X = filas.reindex(columns=self.columnas_total).astype(float).fillna(RELLENO_NAN)
        total = np.clip(np.asarray(self.modelo_total.predict(X), dtype=float), 0.0, None)
        return filas[CLAVES_TD].assign(total_m3ha=total)

    def predecir(self, features_turno: pd.DataFrame, ciclos_hist: pd.DataFrame) -> pd.DataFrame:
        """Plan en formato largo (1 fila por ciclo) cuyo total por turno-día es el del modelo directo."""
        columnas = [c for c in super().columnas_turno() if c in features_turno.columns]
        base = features_turno[[*CLAVES_TD, *columnas]].reset_index(drop=True)
        n = self.predecir_n_ciclos(base)
        filas = base.loc[base.index.repeat(n), CLAVES_TD].reset_index(drop=True)
        filas["n_ciclos"] = np.repeat(n, n)
        filas["Ciclo"] = np.concatenate([np.arange(1, k + 1) for k in n])
        filas = construir_features_ciclo(filas, base, ciclos_hist)
        plan = escalar_al_total(self.predecir_ciclos(filas), self.predecir_total(features_turno, ciclos_hist))
        plan["duracion_min"] = self.duracion(plan, plan["riego_m3ha"])
        if "riego_m3ha_p10" in plan:
            plan["duracion_min_p10"] = self.duracion(plan, plan["riego_m3ha_p10"])
            plan["duracion_min_p90"] = self.duracion(plan, plan["riego_m3ha_p90"])
        return self.armar_horario(plan)


def escalar_al_total(ciclos: pd.DataFrame, totales: pd.DataFrame) -> pd.DataFrame:
    """Escala los m³/ha de los ciclos de cada turno-día para que sumen ``total_m3ha``.

    El rango p10–p90 se escala con el mismo factor. Si falta el total o los ciclos suman 0, no se toca.
    """
    out = ciclos.copy()
    suma = out.groupby(CLAVES_TD)["riego_m3ha"].transform("sum").to_numpy(dtype=float)
    objetivo = out[CLAVES_TD].merge(totales[[*CLAVES_TD, "total_m3ha"]], on=CLAVES_TD, how="left")["total_m3ha"]
    objetivo = objetivo.to_numpy(dtype=float)
    factor = np.where((suma > 0) & np.isfinite(objetivo), objetivo / np.where(suma > 0, suma, 1.0), 1.0)
    for columna in ("riego_m3ha", "riego_m3ha_p10", "riego_m3ha_p90"):
        if columna in out:
            out[columna] = out[columna].to_numpy(dtype=float) * factor
    return out
