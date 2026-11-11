"""Único lugar donde se traducen las columnas de la BD (minúsculas) a los nombres de ``riego_ml``.

Las tablas usan ``snake_case`` en minúsculas; ``riego_ml`` usa los nombres de sus DataFrames
(``T_media``, ``ETo_mm``, ``hum_45cm_cierre``...). Todo el backend pasa por estos mapeos para leer
o escribir datos que van al modelo; los tests comprueban que coinciden con ``riego_ml``.
"""

from __future__ import annotations

# ambiente_diario (columna de la BD -> columna de riego_ml.dataset.unir.columnas_ambiente()).
AMBIENTE_BD_A_ML: dict[str, str] = {
    "t_media": "T_media",
    "t_max": "T_max",
    "t_min": "T_min",
    "hr_media": "HR_media",
    "hr_min": "HR_min",
    "hr_max": "HR_max",
    "eto_mm": "ETo_mm",
    "dpv_media": "DPV_media",
    "dpv_max": "DPV_max",
    "viento_media": "Viento_media",
    "lluvia_mm": "Lluvia_mm",
    "rad_max": "Rad_max",
    "rad_media": "Rad_media",
    "horas_t30": "horas_T30",
    "meteo_lecturas": "meteo_lecturas",
    "hum_15cm_media": "hum_15cm_media",
    "hum_30cm_media": "hum_30cm_media",
    "hum_45cm_media": "hum_45cm_media",
    "hum_60cm_media": "hum_60cm_media",
    "hum_75cm_media": "hum_75cm_media",
    "hum_90cm_media": "hum_90cm_media",
    "hum_zona_radicular_media": "hum_zona_radicular_media",
    "hum_linea_estres_media": "hum_linea_estres_media",
    "hum_15cm_cierre": "hum_15cm_cierre",
    "hum_30cm_cierre": "hum_30cm_cierre",
    "hum_45cm_cierre": "hum_45cm_cierre",
    "hum_60cm_cierre": "hum_60cm_cierre",
    "hum_75cm_cierre": "hum_75cm_cierre",
    "hum_90cm_cierre": "hum_90cm_cierre",
    "hum_zona_radicular_cierre": "hum_zona_radicular_cierre",
    "hum_linea_estres_cierre": "hum_linea_estres_cierre",
    "hum_45cm_rango": "hum_45cm_rango",
    "hum_60cm_rango": "hum_60cm_rango",
    "suelo_horas": "suelo_horas",
    "mds_contraccion_um": "mds_contraccion_um",
    "crecimiento_tronco_um": "crecimiento_tronco_um",
    "estres_planta_ps": "estres_planta_ps",
    "ndvi_medio": "ndvi_medio",
}
AMBIENTE_ML_A_BD: dict[str, str] = {ml: bd for bd, ml in AMBIENTE_BD_A_ML.items()}
BANDERAS_AMBIENTE = ("tiene_meteo", "tiene_suelo", "tiene_planta")

# meteo_lectura (BD -> formato de riego_ml.sources.meteo después de renombrar COLUMNAS_ORIGEN).
METEO_BD_A_ML: dict[str, str] = {
    "temp": "T",
    "temp_max": "T_max",
    "temp_min": "T_min",
    "hr": "HR",
    "hr_max": "HR_max",
    "rad": "Rad",
    "eto": "ETo",
    "dpv": "DPV",
    "viento": "Viento",
    "lluvia": "Lluvia",
}
METEO_ML_A_BD: dict[str, str] = {ml: bd for bd, ml in METEO_BD_A_ML.items()}

# phytech_suelo_horario (BD -> hoja Suelo_horario de riego_ml.sources.phytech_crudo).
# Las columnas de medición tienen el mismo nombre; solo cambia la bandera.
SUELO_MEDICIONES = (
    "hum_15cm", "hum_30cm", "hum_45cm", "hum_60cm", "hum_75cm", "hum_90cm",
    "temp_15cm", "temp_30cm", "temp_60cm", "temp_90cm",
    "hum_zona_radicular", "hum_saturacion", "hum_linea_estres", "hum_zona_radicular_norm_pct",
)
SUELO_BD_A_ML: dict[str, str] = {"hay_dato": "hay_dato_phytech", **{c: c for c in SUELO_MEDICIONES}}

# phytech_planta_diario (BD -> hoja Planta_diario). Mismos nombres.
PLANTA_MEDICIONES = (
    "mds_contraccion_um", "crecimiento_tronco_um", "estres_planta_ps",
    "tamano_fruto_mm", "crecimiento_fruto_mm",
)

# Clases de NDVI: ndvi_imagen.clases guarda [{"clase", "color", "ndvi_min", "ndvi_max",
# "percent"}] y se vuelve a las columnas class{k}_* del archivo NdviImages.
NDVI_N_CLASES = 5
