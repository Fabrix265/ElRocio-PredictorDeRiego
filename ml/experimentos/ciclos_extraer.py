"""Paso 1 del experimento (venv del backend): riego 05–18/11 del Fabric de El Rocío (solo lectura) y
ambiente diario de riego_dev (local). No escribe en ninguna base.

Uso (desde backend/, con RIEGO_SIN_ENV_FILE=1 y DATABASE_URL de riego_dev):
    .venv/Scripts/python ../ml/data/reentreno_2026-11-19/paso1_extraer.py
"""
import datetime as dt
import os
from pathlib import Path

import pandas as pd

assert os.environ.get("RIEGO_SIN_ENV_FILE") == "1" and "localhost" in os.environ.get("DATABASE_URL", ""), \
    "Exporta RIEGO_SIN_ENV_FILE=1 y DATABASE_URL de riego_dev"

from app.db.session import nueva_sesion  # noqa: E402
from app.integraciones.galileo import adaptador  # noqa: E402
from app.integraciones.galileo.cliente import ClienteGalileo  # noqa: E402
from app.models import Fundo, Modulo  # noqa: E402
from app.repositories import riego as repo_riego  # noqa: E402
from app.services import ambiente_service  # noqa: E402

AQUI = Path(__file__).resolve().parents[1] / "data" / "exp_ciclos"
DESDE, HASTA = dt.date(2026, 11, 5), dt.date(2026, 11, 20)

with nueva_sesion() as db:
    modulo = db.query(Modulo).filter(Modulo.codigo == "EN01-MOD5").one()
    fundo = db.get(Fundo, modulo.fundo_id)
    from types import SimpleNamespace
    turnos = [SimpleNamespace(id=t.id, codigo=t.codigo, valvula_controlador=t.valvula_controlador, area_ha=t.area_ha)
              for t in repo_riego.turnos_de_modulo(db, modulo.id)]
    ambiente = ambiente_service.ambiente_para_modelo(db, fundo)
    db.rollback()

cliente = ClienteGalileo()
try:
    columnas = cliente.columnas()
    crudas = cliente.filas(DESDE, HASTA)
finally:
    cliente.cerrar()
r = adaptador.adaptar(crudas, columnas, turnos)
print("Fabric:", r.resumen())

por_id = {t.id: t for t in turnos}
filas = []
for (turno_id, fecha), ciclos in sorted(r.grupos.items(), key=lambda x: (x[0][1], por_id[x[0][0]].codigo)):
    if not DESDE <= fecha <= HASTA:
        continue
    for c in ciclos:
        filas.append({"fecha": fecha, "turno": por_id[turno_id].codigo, "valvula": por_id[turno_id].valvula_controlador,
                      **{k: c[k] for k in ("inicio_min", "fin_min", "duracion_min", "riego_m3", "riego_m3ha", "area_ha")}})
riego = pd.DataFrame(filas)
riego.to_csv(AQUI / "riego_fabric.csv", index=False)
ambiente.to_csv(AQUI / "ambiente_riego_dev.csv", index=False)
print("riego:", len(riego), "ciclos;", riego.groupby("fecha").size().to_dict())
print("ambiente:", ambiente["Fecha"].min().date(), "a", ambiente["Fecha"].max().date(), ambiente.shape)
