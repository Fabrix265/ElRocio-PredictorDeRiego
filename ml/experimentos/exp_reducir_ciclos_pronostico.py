"""Predicción de ejemplo para el 21/11 (hoy) y el 22/11 (mañana) con datos hasta el 20/11.

- Cada candidato se entrena con todo lo conocido hasta el 20/11.
- 21/11: un paso adelante (riego y clima reales hasta el 20/11).
- 22/11: el 21/11 todavía no cerró; se completa con lo predicho para el 21/11 (como hace el backend):
  total predicho, misma estructura de ciclos y horario del 20/11, y clima del 20/11 repetido.
- El modelo en uso (plan_riego/portable) se encadena igual, con sus propios ciclos del 21/11.

Uso (desde ml/): .venv/Scripts/python experimentos/exp_reducir_ciclos_pronostico.py [candidato ...]
"""
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import exp_reducir_ciclos as e  # noqa: E402
from riego_ml.dataset.features import columnas_features  # noqa: E402
from riego_ml.dataset.limpieza import CLAVES_TD, tabla_turno_dia  # noqa: E402

D21, D22 = pd.Timestamp("2026-11-21"), pd.Timestamp("2026-11-22")
elegidos = sys.argv[1:] or ["directo_rf_riego_clima", "resid7_rf_riego_clima"]

ciclos, td, ambiente, _ = e.cargar_datos()
tabla = e.construir_tabla(td, ambiente)
fuera = {"Turno", "riego_total_m3ha", "n_ciclos", "dia_incompleto", "ref_ayer", "ref_media3", "ref_media7", "ref_mediana7"}
features = [c for c in columnas_features(tabla, False, True) if c not in fuera]
cands = {c.nombre: c for c in e.candidatos(features)}
train = tabla[tabla["dia_incompleto"] == 0]
turnos = sorted(td["Turno"].unique())


def claves(dia):
    base = td[td["Fecha"] == td["Fecha"].max()][["Fundo", "Modulo", "Turno"]]
    return base.assign(Fecha=dia)[CLAVES_TD]


def td_con_21(totales: dict[str, float]) -> pd.DataFrame:
    """Agrega un 21/11 sintético: total predicho con la estructura del 20/11."""
    d20 = td[td["Fecha"] == pd.Timestamp("2026-11-20")].copy()
    ciclo_medio = d20["riego_total_m3ha"] / d20["n_ciclos"]
    d21 = d20.assign(Fecha=D21, riego_total_m3ha=d20["Turno"].map(totales))
    d21["n_ciclos"] = np.maximum(1, (d21["riego_total_m3ha"] / ciclo_medio).round()).astype(int)
    d21["riego_total_m3"] = d21["riego_total_m3ha"] * d21["area_ha"]
    d21["duracion_total_min"] = d20["duracion_total_min"] / d20["riego_total_m3ha"] * d21["riego_total_m3ha"]
    return pd.concat([td, d21], ignore_index=True)


amb22 = pd.concat([ambiente, ambiente[ambiente["Fecha"] == ambiente["Fecha"].max()].assign(Fecha=D21)], ignore_index=True)
filas = []
for nombre in elegidos:
    c = cands[nombre].ajustar(train)
    t21 = e.construir_tabla(td, ambiente, claves(D21))
    p21 = dict(zip(t21["Turno"], c.predecir(t21)))
    t22 = e.construir_tabla(td_con_21(p21), amb22, claves(D22))
    p22 = dict(zip(t22["Turno"], c.predecir(t22)))
    for dia, p in (("21/11", p21), ("22/11", p22)):
        filas += [{"modelo": nombre, "fecha": dia, "turno": t, "m3ha": p[t]} for t in turnos]

# Referencias simples, encadenadas igual (el 21/11 sintético = lo que predijo la referencia)
for ref in ("ref_mediana7", "ref_media7"):
    t21 = e.construir_tabla(td, ambiente, claves(D21))
    p21 = dict(zip(t21["Turno"], t21[ref]))
    t22 = e.construir_tabla(td_con_21(p21), amb22, claves(D22))
    p22 = dict(zip(t22["Turno"], t22[ref]))
    for dia, p in (("21/11", p21), ("22/11", p22)):
        filas += [{"modelo": ref, "fecha": dia, "turno": t, "m3ha": p[t]} for t in turnos]

# Modelo en uso, encadenado
plan = joblib.load(e.RAIZ_ML / "models/plan_riego/portable/modelo_plan_riego.joblib")
t21 = e.construir_tabla(td, ambiente, claves(D21))
c21 = plan.predecir(t21, ciclos)
filas += [{"modelo": "actual_plan", "fecha": "21/11", "turno": t, "m3ha": g.riego_m3ha.sum()} for t, g in c21.groupby("Turno")]
nuevos = c21.assign(area_ha=c21["riego_m3"] / c21["riego_m3ha"])
ciclos21 = pd.concat([ciclos, nuevos[[x for x in ciclos.columns if x in nuevos.columns]]], ignore_index=True)
t22 = e.construir_tabla(tabla_turno_dia(ciclos21), amb22, claves(D22))
c22 = plan.predecir(t22, ciclos21)
filas += [{"modelo": "actual_plan", "fecha": "22/11", "turno": t, "m3ha": g.riego_m3ha.sum()} for t, g in c22.groupby("Turno")]

df = pd.DataFrame(filas)
ens = df[df.modelo.isin(["ref_mediana7", "directo_rf_riego_clima"])].groupby(["fecha", "turno"], as_index=False)["m3ha"].mean()
df = pd.concat([df, ens.assign(modelo="ens_med7_rfclima")], ignore_index=True)
df["pulsos_9_8"] = e.pulsos(df["m3ha"])
df.to_csv(e.SALIDA / "pronostico_21_22.csv", index=False)
pd.set_option("display.width", 200)
print(df.pivot_table(index=["fecha", "turno"], columns="modelo", values="m3ha").round(1).to_string())
print(df.pivot_table(index=["fecha", "turno"], columns="modelo", values="pulsos_9_8").to_string())
