"""Adaptador del bucle de generación (§3.1) sobre riego_ml, sin cambiar su lógica.

- El plan de cada día sale de ``plan.predecir`` con las features de ``features_para_fechas``: el
  mismo procedimiento que ``riego_ml.modeling.prediccion.planificar``.
- Los días que se generan se agregan al historial con ``_agregar_al_historial`` (igual que
  ``planificar``); los que no se tocan ya están en el historial con su riego vigente o su versión
  de referencia (``historial_bd.construir_historial``). Si todos los días son nuevos, el resultado es
  idéntico a ``planificar``.
- Además, por turno, se guarda la "foto" de entradas (features turno-día y de ciclo) y
  ``alternativas_n``: la salida del modelo forzando n = 1..max_ciclos con la misma ruta de
  ``PlanRiego.predecir`` (para cambiar el n° de ciclos al editar, §3.4).
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from riego_ml.dataset.features import construir_features_ciclo
from riego_ml.dataset.limpieza import CLAVES_TD
from riego_ml.dataset.preparar import Historial, features_para_fechas
from riego_ml.modeling.prediccion import _agregar_al_historial

COLUMNAS_CICLO_FOTO = ("Ciclo", "n_ciclos", "ciclo_rel")


def json_seguro(valor: Any) -> Any:
    """Valores de pandas/numpy a JSON (NaN → None, fechas → texto ISO)."""
    if isinstance(valor, dict):
        return {str(k): json_seguro(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [json_seguro(v) for v in valor]
    if isinstance(valor, (dt.date, dt.datetime)):  # pd.Timestamp es datetime
        return valor.isoformat()
    if isinstance(valor, np.generic):
        valor = valor.item()
    if isinstance(valor, float) and (math.isnan(valor) or math.isinf(valor)):
        return None
    if valor is pd.NaT or valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    return valor


def hhmm_a_min(texto: Any) -> float | None:
    if not isinstance(texto, str) or ":" not in texto:
        return None
    h, m = texto.split(":", 1)
    return float(int(h) * 60 + int(m))


@dataclass
class PrediccionDia:
    fecha: dt.date
    plan: pd.DataFrame                      # salida de plan.predecir (1 fila por ciclo)
    features_turno: dict[str, dict]         # Turno -> features turno-día
    features_ciclo: dict[str, list[dict]]   # Turno -> features por ciclo (con el n del modelo)
    alternativas: dict[str, dict[int, list[dict]]] = field(default_factory=dict)  # Turno -> n -> ciclos
    factor: dict[str, float] = field(default_factory=dict)  # Turno -> min por m3/ha
    # Riego por pulsos (``aplicar_pulsos``): resumen del cálculo y ciclos originales del modelo.
    calculo: dict[str, Any] | None = None
    plan_modelo: dict[str, list[dict]] = field(default_factory=dict)  # Turno -> ciclos del modelo


def _base(plan: Any, features: pd.DataFrame) -> pd.DataFrame:
    columnas = [c for c in plan.columnas_turno() if c in features.columns]
    return features[[*CLAVES_TD, *columnas]].reset_index(drop=True)


def _con_n(plan: Any, base: pd.DataFrame, ciclos_hist: pd.DataFrame, n: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``PlanRiego.predecir`` con el n° de ciclos forzado a ``n`` en todos los turnos."""
    nn = np.full(len(base), n, dtype=int)
    filas = base.loc[base.index.repeat(nn), CLAVES_TD].reset_index(drop=True)
    filas["n_ciclos"] = np.repeat(nn, nn)
    filas["Ciclo"] = np.concatenate([np.arange(1, k + 1) for k in nn])
    filas = construir_features_ciclo(filas, base, ciclos_hist)
    salida = plan.predecir_ciclos(filas)
    salida["duracion_min"] = plan.duracion(salida, salida["riego_m3ha"])
    if "riego_m3ha_p10" in salida:
        salida["duracion_min_p10"] = plan.duracion(salida, salida["riego_m3ha_p10"])
        salida["duracion_min_p90"] = plan.duracion(salida, salida["riego_m3ha_p90"])
    return plan.armar_horario(salida), filas


def ciclos_de(plan_turno: pd.DataFrame) -> list[dict]:
    filas = []
    for _, c in plan_turno.sort_values("Ciclo").iterrows():
        filas.append(json_seguro({
            "ciclo": int(c["Ciclo"]), "riego_m3ha": c["riego_m3ha"], "riego_m3": c["riego_m3"],
            "duracion_min": c["duracion_min"], "inicio_min": c["inicio_min"], "fin_min": c["fin_min"],
            "hora_inicio": c["hora_inicio"], "hora_fin": c["hora_fin"],
            "fin_dia_siguiente": bool(c["fin_dia_siguiente"]),
            "m3ha_p10": c.get("riego_m3ha_p10"), "m3ha_p90": c.get("riego_m3ha_p90"),
            "duracion_p10": c.get("duracion_min_p10"), "duracion_p90": c.get("duracion_min_p90"),
            "inicio_desde_min": hhmm_a_min(c.get("hora_inicio_desde")),
            "inicio_hasta_min": hhmm_a_min(c.get("hora_inicio_hasta")),
        }))
    return filas


def predecir_dia(plan: Any, historial: Historial, fecha: dt.date, config: Any) -> PrediccionDia:
    """Plan de ``fecha`` (todos los turnos conocidos) con foto de entradas y alternativas."""
    dia = pd.Timestamp(fecha)
    features = features_para_fechas(historial, [dia], config)
    resultado = plan.predecir(features, historial.ciclos)

    base = _base(plan, features)
    factores = plan.factor_duracion(base)
    n_modelo = dict(zip(resultado["Turno"], resultado["n_ciclos"]))
    pred = PrediccionDia(fecha=fecha, plan=resultado, features_turno={}, features_ciclo={})
    for i, fila in base.iterrows():
        turno = fila["Turno"]
        pred.features_turno[turno] = json_seguro({k: v for k, v in fila.items() if k not in CLAVES_TD})
        pred.factor[turno] = float(factores[i])
    for n in range(1, int(plan.max_ciclos) + 1):
        salida, filas = _con_n(plan, base, historial.ciclos, n)
        for turno, g in salida.groupby("Turno", sort=False):
            pred.alternativas.setdefault(turno, {})[n] = ciclos_de(g)
        for turno, g in filas.groupby("Turno", sort=False):
            if int(n_modelo.get(turno, 0)) == n:
                extra = [c for c in g.columns if c not in CLAVES_TD and c not in base.columns]
                pred.features_ciclo[turno] = [json_seguro(r) for r in g[extra].to_dict("records")]
    return pred


def agregar(historial: Historial, prediccion: PrediccionDia) -> Historial:
    """El plan del día pasa a ser el "riego de ayer" del día siguiente (como ``planificar``).

    Llamar **antes** de ``aplicar_pulsos``: el historial lleva lo que predijo el modelo, no los
    pulsos (el modelo no se entrenó con riegos por pulsos)."""
    return _agregar_al_historial(historial, prediccion.plan)


def aplicar_pulsos(prediccion: PrediccionDia, parametros: Any, orden_turnos: list[str],
                   areas: dict[str, float]) -> PrediccionDia:
    """Reemplaza los ciclos del modelo por el plan por pulsos (``app.services.calculo_pulsos``).

    Del modelo solo se usa el total de m³/ha de cada turno. ``orden_turnos``: orden de riego
    dentro de cada bloque. ``areas``: ha por turno (si falta, la del plan del modelo)."""
    from app.services import calculo_pulsos

    plan = prediccion.plan
    totales: dict[str, float] = {}
    areas_plan: dict[str, float] = {}
    for turno in [t for t in orden_turnos if t in set(plan["Turno"])]:
        g = plan[plan["Turno"] == turno]
        totales[turno] = float(g["riego_m3ha"].sum())
        m3ha = float(g["riego_m3ha"].iloc[0])
        areas_plan[turno] = float(g["riego_m3"].iloc[0] / m3ha) if m3ha else areas.get(turno, 0.0)
    if not totales:
        return prediccion
    resultado = calculo_pulsos.calcular(totales, areas_plan, parametros)
    filas = []
    for turno, plan_turno in resultado.turnos.items():
        for c in plan_turno.ciclos:
            filas.append({"Turno": turno, "n_ciclos": plan_turno.n_ciclos, "Ciclo": c.ciclo,
                          "riego_m3ha": c.riego_m3ha, "riego_m3": c.riego_m3, "duracion_min": c.duracion_min,
                          "inicio_min": c.inicio_min, "fin_min": c.fin_min, "hora_inicio": c.hora_inicio,
                          "hora_fin": c.hora_fin, "fin_dia_siguiente": int(c.fin_dia_siguiente)})
    nuevo = pd.DataFrame(filas, columns=["Turno", "n_ciclos", "Ciclo", "riego_m3ha", "riego_m3", "duracion_min",
                                         "inicio_min", "fin_min", "hora_inicio", "hora_fin", "fin_dia_siguiente"])
    factor = resultado.derivados.min_por_m3ha
    return PrediccionDia(
        fecha=prediccion.fecha, plan=nuevo, features_turno=prediccion.features_turno,
        features_ciclo=prediccion.features_ciclo,
        alternativas=calculo_pulsos.alternativas(resultado, totales, areas_plan, parametros),
        factor={t: factor for t in totales},
        calculo=calculo_pulsos.detalle(resultado, parametros),
        plan_modelo={t: ciclos_de(g) for t, g in plan.groupby("Turno", sort=False)},
    )
