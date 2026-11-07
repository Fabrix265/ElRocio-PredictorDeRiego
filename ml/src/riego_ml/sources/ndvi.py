"""NDVI (vigor de la vegetación) de las imágenes satelitales de Phytech.

Los archivos ``NdviImages_<año>_area<id>.xlsx`` traen, por imagen, cinco
clases de NDVI con su rango y el % del plot en cada una. El NDVI medio del
plot se estima como el promedio de los centros de clase ponderado por %.
Hay una imagen cada ~10 días, así que es una señal lenta (vigor del cultivo).
"""

from __future__ import annotations

import glob
import os
from pathlib import Path

import pandas as pd

from riego_ml.utils.tiempo import norm_text


def leer_ndvi(carpeta: str | Path, area_id: int, plot_id: int, fundo: str) -> tuple[pd.DataFrame, dict]:
    patron = os.path.join(str(carpeta), "**", f"NdviImages_*_area{area_id}.xlsx")
    archivos = sorted(glob.glob(patron, recursive=True))
    if not archivos:
        return pd.DataFrame(columns=["Fundo", "Fecha", "ndvi_medio"]), {"NDVI: imágenes": 0}
    df = pd.concat([pd.read_excel(a) for a in archivos], ignore_index=True)
    df = df[(df["entity_id"] == plot_id) & (~df["no_vegetation"].fillna(False).astype(bool))].copy()
    total = 0.0
    peso = 0.0
    for k in range(5):
        centro = (df[f"class{k}_ndvi_min"] + df[f"class{k}_ndvi_max"]) / 2
        total = total + centro * df[f"class{k}_percent"]
        peso = peso + df[f"class{k}_percent"]
    df["ndvi_medio"] = total / peso
    df["Fecha"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df["Fundo"] = norm_text(pd.Series(fundo, index=df.index))
    out = (
        df.dropna(subset=["Fecha", "ndvi_medio"])
        .groupby(["Fundo", "Fecha"], as_index=False)["ndvi_medio"].mean()
        .round(4)
    )
    diag = {
        "NDVI: imágenes del plot": len(out),
        "NDVI: rango de fechas": (f"{out['Fecha'].min():%Y-%m-%d} a {out['Fecha'].max():%Y-%m-%d}"
                                  if len(out) else "sin datos"),
    }
    return out, diag
