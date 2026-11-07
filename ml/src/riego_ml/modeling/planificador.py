"""Armado del plan de riego a partir de los modelos entrenados.

Para cada turno-día:

1. El modelo de ``n_ciclos`` estima cuántos ciclos hay.
2. Para cada ciclo k = 1..n_ciclos se estiman ``riego_m3ha`` e ``inicio_min``
   (y, si hay modelos de rango, un intervalo p10–p90 para cada uno).
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

from riego_ml.dataset.features import construir_features_ciclo, features_solo_ciclo
from riego_ml.dataset.limpieza import CLAVES_TD
from riego_ml.utils.tiempo import MINUTOS_DIA, minutes_to_hhmm

TARGETS = ("n_ciclos", "riego_m3ha", "inicio_min")
COLUMNA_CAUDAL = "min_por_m3ha_30d"


@dataclass
class PlanRiego:
    modelos: dict[str, Any]
    features: dict[str, list[str]]
    max_ciclos: int
    min_por_m3ha: dict[str, float]
    area_ha: dict[str, float]
    rango_m3ha: tuple[float, float]
    pausa_min: float = 0.0
    rangos: dict[str, Any] = field(default_factory=dict)
    caudal_dinamico: bool = False  # True: duración con el caudal de los últimos 30 días
    elegidos: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ #
    def columnas_turno(self) -> list[str]:
        """Columnas turno-día que necesita algún modelo (unión, sin claves ni columnas de ciclo)."""
        todas = [c for t in TARGETS for c in self.features[t]]
        for modelo in self.rangos.values():
            todas += list(getattr(modelo, "columnas_", []))
        de_ciclo = set(features_solo_ciclo(True))
        todas.append(COLUMNA_CAUDAL)  # siempre se necesita para derivar la duración
        return [c for c in dict.fromkeys(todas) if c not in CLAVES_TD and c not in de_ciclo]

    def predecir_n_ciclos(self, features_turno: pd.DataFrame) -> np.ndarray:
        pred = self.modelos["n_ciclos"].predict(features_turno[self.features["n_ciclos"]])
        return np.clip(np.rint(np.asarray(pred, dtype=float)), 1, self.max_ciclos).astype(int)

    def predecir_ciclos(self, filas_ciclo: pd.DataFrame) -> pd.DataFrame:
        """Predice m3/ha e inicio (y sus rangos) para filas con features de ciclo."""
        out = filas_ciclo.copy()
        m3ha = self.modelos["riego_m3ha"].predict(out[self.features["riego_m3ha"]])
        out["riego_m3ha"] = np.clip(m3ha, *self.rango_m3ha)
        inicio = self.modelos["inicio_min"].predict(out[self.features["inicio_min"]])
        out["inicio_min"] = np.clip(inicio, 0.0, MINUTOS_DIA - 1.0)
        for target, modelo in self.rangos.items():
            bajo, alto = modelo.predict(out[modelo.columnas_])
            # el rango siempre contiene a la predicción central
            out[f"{target}_p10"] = np.minimum(bajo, out[target])
            out[f"{target}_p90"] = np.maximum(alto, out[target])
        if "riego_m3ha_p10" in out:
            out[["riego_m3ha_p10", "riego_m3ha_p90"]] = out[["riego_m3ha_p10", "riego_m3ha_p90"]].clip(*self.rango_m3ha)
        if "inicio_min_p10" in out:
            out[["inicio_min_p10", "inicio_min_p90"]] = out[["inicio_min_p10", "inicio_min_p90"]].clip(0, MINUTOS_DIA - 1)
        return out

    def factor_duracion(self, filas: pd.DataFrame) -> np.ndarray:
        """Minutos por m3/ha: caudal reciente del turno (30 días) o, si falta, el histórico."""
        historico = filas["Turno"].map(self.min_por_m3ha).fillna(np.nanmedian(list(self.min_por_m3ha.values())))
        if self.caudal_dinamico and COLUMNA_CAUDAL in filas:
            return filas[COLUMNA_CAUDAL].fillna(historico).to_numpy(dtype=float)
        return historico.to_numpy(dtype=float)

    def duracion(self, filas: pd.DataFrame, m3ha: pd.Series) -> np.ndarray:
        return np.asarray(m3ha, dtype=float) * self.factor_duracion(filas)

    def predecir(self, features_turno: pd.DataFrame, ciclos_hist: pd.DataFrame) -> pd.DataFrame:
        """Plan en formato largo: 1 fila por ciclo programado."""
        columnas = [c for c in self.columnas_turno() if c in features_turno.columns]
        base = features_turno[[*CLAVES_TD, *columnas]].reset_index(drop=True)
        n = self.predecir_n_ciclos(base)
        filas = base.loc[base.index.repeat(n), CLAVES_TD].reset_index(drop=True)
        filas["n_ciclos"] = np.repeat(n, n)
        filas["Ciclo"] = np.concatenate([np.arange(1, k + 1) for k in n])
        filas = construir_features_ciclo(filas, base, ciclos_hist)
        plan = self.predecir_ciclos(filas)
        plan["duracion_min"] = self.duracion(plan, plan["riego_m3ha"])
        if "riego_m3ha_p10" in plan:
            plan["duracion_min_p10"] = self.duracion(plan, plan["riego_m3ha_p10"])
            plan["duracion_min_p90"] = self.duracion(plan, plan["riego_m3ha_p90"])
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
        if "riego_m3ha_p10" in plan:
            columnas += ["riego_m3ha_p10", "riego_m3ha_p90", "duracion_min_p10", "duracion_min_p90"]
        if "inicio_min_p10" in plan:
            plan["hora_inicio_desde"] = plan["inicio_min_p10"].map(minutes_to_hhmm)
            plan["hora_inicio_hasta"] = plan["inicio_min_p90"].map(minutes_to_hhmm)
            columnas += ["hora_inicio_desde", "hora_inicio_hasta"]
        redondeo = {c: 2 if "m3ha" in c else 1 for c in columnas if c.startswith(("riego", "duracion", "inicio", "fin_min"))}
        return plan[columnas].round(redondeo)


def plan_ancho(plan: pd.DataFrame, max_ciclos: int) -> pd.DataFrame:
    """1 fila por turno-día: n_ciclos y, por cada ciclo, m3/ha, duración, inicio y fin."""
    con_rango = "riego_m3ha_p10" in plan
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
            if con_rango:
                fila[f"ciclo{k}_m3ha_rango"] = "" if vacio else (
                    f"{c['riego_m3ha_p10'].iloc[0]:.1f} – {c['riego_m3ha_p90'].iloc[0]:.1f}")
            fila[f"ciclo{k}_duracion_min"] = np.nan if vacio else c["duracion_min"].iloc[0]
            fila[f"ciclo{k}_hora_inicio"] = "" if vacio else c["hora_inicio"].iloc[0]
            if "hora_inicio_desde" in c:
                fila[f"ciclo{k}_inicio_rango"] = "" if vacio else (
                    f"{c['hora_inicio_desde'].iloc[0]} – {c['hora_inicio_hasta'].iloc[0]}")
            fila[f"ciclo{k}_hora_fin"] = "" if vacio else c["hora_fin"].iloc[0]
        filas.append(fila)
    return pd.DataFrame(filas)
