"""Paso 1 - Une las tres fuentes usando el registro de riego como base.

* ``ambiente_diario``: calendario continuo (1 fila por Fundo y día) con la
  meteorología diaria y el suelo/planta de Phytech. Es la tabla de la que el
  paso 2 saca los rezagos (día anterior, acumulados) sin huecos de calendario.
* ``riego_unido``: cada ciclo de ``data_riego`` con el ambiente del MISMO día
  (llave Fundo + Fecha). Sirve para revisar y auditar el cruce; el modelo no
  usa estas columnas del mismo día para no "ver el futuro".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from riego_ml.sources.meteo import COLUMNAS_DIARIAS, leer_meteo, meteo_diaria
from riego_ml.sources.phytech import PLANTA_VARS, columnas_suelo_diario, leer_phytech
from riego_ml.sources.riego import leer_riego

CLAVES_DIA = ["Fundo", "Fecha"]


@dataclass
class DatasetUnido:
    riego_unido: pd.DataFrame
    ambiente_diario: pd.DataFrame
    diagnostico: dict = field(default_factory=dict)


def columnas_ambiente() -> list[str]:
    return [*COLUMNAS_DIARIAS, *columnas_suelo_diario(), *PLANTA_VARS]


def construir_ambiente_diario(meteo: pd.DataFrame, phytech: pd.DataFrame, fundos: list[str]) -> pd.DataFrame:
    """Calendario diario continuo por fundo con meteo + Phytech."""
    fechas = pd.concat([meteo["Fecha"], phytech["Fecha"]])
    calendario = pd.MultiIndex.from_product(
        [fundos, pd.date_range(fechas.min(), fechas.max(), freq="D")], names=CLAVES_DIA
    ).to_frame(index=False)
    ambiente = (
        calendario.merge(meteo, on=CLAVES_DIA, how="left", validate="one_to_one")
        .merge(phytech, on=CLAVES_DIA, how="left", validate="one_to_one")
    )
    ambiente["tiene_meteo"] = ambiente["T_media"].notna().astype(int)
    ambiente["tiene_suelo"] = ambiente["suelo_horas"].notna().astype(int)
    ambiente["tiene_planta"] = ambiente["mds_contraccion_um"].notna().astype(int)
    return ambiente[[*CLAVES_DIA, *columnas_ambiente(), "tiene_meteo", "tiene_suelo", "tiene_planta"]]


def unir_fuentes(
    ruta_riego: Path,
    ruta_meteo: Path,
    ruta_phytech: Path,
    hoja_riego: str = "MOD5",
    phytech_project_id: int = 907557,
) -> DatasetUnido:
    diag: dict = {}
    riego, d = leer_riego(ruta_riego, hoja_riego)
    diag.update(d)
    lecturas, d = leer_meteo(ruta_meteo)
    diag.update(d)
    meteo, d = meteo_diaria(lecturas)
    diag.update(d)
    phytech, d = leer_phytech(ruta_phytech, phytech_project_id)
    diag.update(d)

    fundos_riego = set(riego["Fundo"].dropna())
    for nombre, tabla in (("meteo", meteo), ("phytech", phytech)):
        sin_cruce = fundos_riego - set(tabla["Fundo"].dropna())
        if sin_cruce:
            raise ValueError(f"Fundos de riego sin datos de {nombre}: {sorted(sin_cruce)}")

    ambiente = construir_ambiente_diario(meteo, phytech, sorted(fundos_riego))
    unido = riego.merge(ambiente, on=CLAVES_DIA, how="left", validate="many_to_one")

    dias_riego = unido.drop_duplicates(CLAVES_DIA)
    for bandera in ("tiene_meteo", "tiene_suelo", "tiene_planta"):
        diag[f"Unión: % de días de riego con {bandera.split('_')[1]}"] = (
            f"{dias_riego[bandera].fillna(0).mean() * 100:.1f}%"
        )
    diag["Unión: ciclos en el dataset unido"] = len(unido)
    diag["Unión: días en ambiente_diario"] = len(ambiente)
    return DatasetUnido(unido, ambiente, diag)


DICCIONARIO = {
    "Fecha": "Día de inicio del ciclo (llave con meteo y Phytech).",
    "Fundo / Modulo / Turno": "Ubicación del riego. Turno TE01..TE05 = válvula del módulo.",
    "inicio_min / fin_min": "Minutos desde las 00:00 de Fecha (fin puede pasar de 1440).",
    "hora_inicio / hora_fin": "HH:MM de inicio y fin del ciclo.",
    "duracion_min": "Duración del ciclo (columna 'Tiempo de riego (minutos)').",
    "riego_m3 / riego_m3ha": "Volumen del ciclo en m3 y en m3 por hectárea.",
    "area_ha": "Área regada por el turno (riego_m3 / riego_m3ha).",
    "T_* / HR_* / DPV_*": "Temperatura (°C), humedad relativa (%) y déficit de presión de vapor (kPa) del día.",
    "ETo_mm / Lluvia_mm": "Evapotranspiración de referencia y lluvia del día (mm).",
    "Rad_max / Rad_media": "Radiación solar (W/m2).",
    "hum_<prof>cm_media": "Humedad del suelo media del día (% vol.) a esa profundidad.",
    "hum_<prof>cm_cierre": "Humedad del suelo al cierre del día (media 21-23 h).",
    "hum_zona_radicular_* / hum_linea_estres_*": "Humedad de zona radicular y línea de estrés de Phytech.",
    "mds_contraccion_um": "Máxima contracción diaria del tronco (µm).",
    "crecimiento_tronco_um / estres_planta_ps": "Crecimiento del tronco (µm) e índice de estrés de Phytech.",
    "tiene_meteo / tiene_suelo / tiene_planta": "1 si ese día hay dato de la fuente.",
}
