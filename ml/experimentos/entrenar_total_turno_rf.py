"""Entrena el Random Forest del total de m³/ha por turno-día y lo empaqueta para el backend.

- Datos: los de ``exp_reducir_ciclos.cargar_datos`` (histórico + Fabric hasta el 20/11 + ambiente
  de riego_dev), los mismos del experimento.
- Modelo: ``directo_rf_riego_clima`` (el RF del experimento: calendario + riego + clima + ref_*).
- Paquete: ``PlanTotalTurno`` = plan en uso (``models/plan_riego/portable``) + este RF para el total.
  El backend lo carga como cualquier ``PlanRiego`` (``ML_MODEL_PATH``).
- Comprobación: el total que da el paquete para el 21/11 debe coincidir con el del experimento.

Salida: ``models/plan_riego/total_turno_rf/`` (``modelo_plan_riego.joblib`` + ``metadata.json``).
Uso (desde ml/): .venv/Scripts/python experimentos/entrenar_total_turno_rf.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp_reducir_ciclos as e  # noqa: E402
from riego_ml.dataset.features import columnas_features, construir_features_turno  # noqa: E402
from riego_ml.dataset.limpieza import CLAVES_TD  # noqa: E402
from riego_ml.modeling.total_turno import COLUMNAS_REFERENCIA, PlanTotalTurno, agregar_referencias  # noqa: E402

NOMBRE = "directo_rf_riego_clima"
BASE = e.RAIZ_ML / "models/plan_riego/portable"
DESTINO = e.RAIZ_ML / "models/plan_riego/total_turno_rf"
FUERA = {"Turno", "riego_total_m3ha", "n_ciclos", "dia_incompleto", *COLUMNAS_REFERENCIA}


def tabla_entrenamiento(td: pd.DataFrame, ambiente: pd.DataFrame) -> pd.DataFrame:
    claves = td[CLAVES_TD]
    feats = construir_features_turno(claves, td, ambiente, False)
    tabla = claves.merge(td[[*CLAVES_TD, "riego_total_m3ha", "n_ciclos", "dia_incompleto"]], on=CLAVES_TD)
    return agregar_referencias(tabla.merge(feats, on=CLAVES_TD, how="left"), td)


def main() -> None:
    ciclos, td, ambiente, movidos = e.cargar_datos()
    tabla = tabla_entrenamiento(td, ambiente)
    features = [c for c in columnas_features(tabla, False, True) if c not in FUERA]
    cand = {c.nombre: c for c in e.candidatos(features)}[NOMBRE]
    train = tabla[tabla["dia_incompleto"] == 0]
    cand.ajustar(train)
    print(f"Entrenado con {len(train.dropna(subset=['riego_total_m3ha']))} turno-días "
          f"({train.Fecha.min():%Y-%m-%d} a {train.Fecha.max():%Y-%m-%d}), {len(cand.columnas)} variables")

    plan = joblib.load(BASE / "modelo_plan_riego.joblib")
    meta_base = json.loads((BASE / "metadata.json").read_text(encoding="utf-8"))
    version = f"{dt.date.today():%Y-%m-%d}_rf_total"
    metadata = {
        **meta_base,
        "version": version,
        "entrenado": dt.datetime.now().isoformat(timespec="seconds"),
        "base": {"version": meta_base.get("version"), "rango_datos": meta_base.get("rango_datos")},
        "total_turno": {
            "modelo": NOMBRE, "familia": "RandomForestRegressor",
            "params": cand.m.get_params(), "columnas": cand.columnas,
            "rango_datos": f"{train.Fecha.min():%Y-%m-%d} a {train.Fecha.max():%Y-%m-%d}",
            "turno_dias": int(train["riego_total_m3ha"].notna().sum()),
            "ciclos_movidos_medianoche": int(len(movidos)),
            "nota": "El total por turno-día sale del RF; los ciclos del plan base se escalan a ese total.",
        },
    }
    paquete = PlanTotalTurno.desde_plan(plan, cand.m, cand.columnas, metadata=metadata)

    # Comprobación: el paquete (como lo usa el backend) da lo mismo que el experimento para el 21/11.
    dia = pd.Timestamp("2026-11-21")
    claves = td[td["Fecha"] == td["Fecha"].max()][["Fundo", "Modulo", "Turno"]].assign(Fecha=dia)[CLAVES_TD]
    features_21 = construir_features_turno(claves, td, ambiente, False)
    total = paquete.predecir_total(features_21, ciclos).set_index("Turno")["total_m3ha"]
    esperado = pd.Series(cand.predecir(tabla_21 := agregar_referencias(features_21, td)), index=tabla_21["Turno"])
    assert np.allclose(total.sort_index(), esperado.sort_index()), (total, esperado)
    plan_21 = paquete.predecir(features_21, ciclos)
    suma = plan_21.groupby("Turno")["riego_m3ha"].sum()
    assert np.allclose(suma.sort_index(), total.sort_index(), atol=0.05), (suma, total)
    print("21/11 (m³/ha por turno):", {t: round(v, 1) for t, v in total.items()})
    print("Ciclos del plan escalado:", plan_21.groupby("Turno").size().to_dict())

    DESTINO.mkdir(parents=True, exist_ok=True)
    joblib.dump(paquete, DESTINO / "modelo_plan_riego.joblib")
    (DESTINO / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str),
                                           encoding="utf-8")
    print(f"Guardado en {DESTINO} (versión {version})")


if __name__ == "__main__":
    main()
