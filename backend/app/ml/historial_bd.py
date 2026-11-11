"""``Historial`` de riego_ml armado desde la BD (§2.3), base de la predicción (F3).

1. Riego por turno-día: el ``riego_registro`` **vigente** (aplicado o provisional; hay uno solo por
   turno-día). Un registro ``sin_riego`` cuenta como dato (el turno no regó: no aporta ciclos).
   Si se indica ``hasta`` (fecha a planificar) y un turno-día anterior no tiene registro, se usan
   los ciclos de ese turno en la versión de referencia del cronograma de ese día (publicada; si no
   hay, el borrador) y se informa en ``turno_dias_cronograma`` (el día planificado queda
   *preliminar*).
2. DataFrame con ``COLUMNAS_RIEGO``: ``Fecha`` datetime64, textos con ``norm_text`` (el ``Fundo``
   debe ser idéntico al de ``ambiente`` o las variables de clima quedan vacías sin aviso).
3. ``limpiar_ciclos(ciclos, 5.0, 2.0)`` → ``tabla_turno_dia`` → ``ambiente_diario`` (nombres de
   riego_ml) → ``Historial``.

Test de paridad contra la ruta por archivos: ``tests/test_paridad_historico.py``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd
from riego_ml.dataset.limpieza import limpiar_ciclos, tabla_turno_dia
from riego_ml.dataset.preparar import Historial
from riego_ml.sources.riego import COLUMNAS_RIEGO
from riego_ml.utils.tiempo import norm_text
from sqlalchemy.orm import Session

from app.core.errores import NoEncontrado
from app.models import Fundo, Modulo
from app.repositories import riego as repo_riego
from app.services import ambiente_service

MIN_DURACION_MIN = 5.0   # preparacion.min_duracion_min de ml/config/pipeline.yaml
MIN_RIEGO_M3HA = 2.0     # preparacion.min_riego_m3ha


@dataclass
class HistorialBD:
    historial: Historial
    # Turno-días sin registro de riego que tomaron los ciclos del cronograma: (fecha, turno).
    turno_dias_cronograma: list[tuple[dt.date, str]] = field(default_factory=list)


def _valvula_numerica(serie: pd.Series) -> pd.Series:
    """Las válvulas son números (6061000): se devuelven como en el Excel si todas lo son."""
    convertida = pd.to_numeric(serie, errors="coerce")
    if convertida.notna().sum() == serie.notna().sum() and convertida.notna().all():
        return convertida.astype("int64")
    return serie


def ciclos_dataframe(filas: list[dict], fundo: str, modulo: str) -> pd.DataFrame:
    """Filas ``{fecha, turno, inicio_min, ...}`` -> DataFrame ``COLUMNAS_RIEGO``."""
    df = pd.DataFrame(filas, columns=[
        "fecha", "turno", "valvula", "inicio_min", "fin_min", "hora_inicio", "hora_fin",
        "fin_dia_siguiente", "duracion_min", "riego_m3", "riego_m3ha", "area_ha",
    ])
    salida = pd.DataFrame({
        "Fecha": pd.to_datetime(df["fecha"]).dt.normalize(),
        "Fundo": norm_text(pd.Series(fundo, index=df.index, dtype="object")),
        "Modulo": norm_text(pd.Series(modulo, index=df.index, dtype="object")),
        "Turno": norm_text(df["turno"].astype("object")),
        "Valvula": _valvula_numerica(df["valvula"]),
        "inicio_min": pd.to_numeric(df["inicio_min"]).astype(float),
        "fin_min": pd.to_numeric(df["fin_min"]).astype(float),
        "hora_inicio": df["hora_inicio"].astype("object"),
        "hora_fin": df["hora_fin"].astype("object"),
        "fin_dia_siguiente": df["fin_dia_siguiente"].astype(bool).astype(int),
        "duracion_min": pd.to_numeric(df["duracion_min"]).astype(float),
        "riego_m3": pd.to_numeric(df["riego_m3"]).astype(float),
        "riego_m3ha": pd.to_numeric(df["riego_m3ha"]).astype(float),
        "area_ha": pd.to_numeric(df["area_ha"]).astype(float),
    })
    salida = salida.sort_values(["Fecha", "Turno", "inicio_min"], kind="stable").reset_index(drop=True)
    return salida[COLUMNAS_RIEGO]


def construir_historial(
    db: Session,
    modulo_id: int,
    *,
    hasta: dt.date | None = None,
    min_duracion_min: float = MIN_DURACION_MIN,
    min_riego_m3ha: float = MIN_RIEGO_M3HA,
) -> HistorialBD:
    """Historial del módulo con los datos **anteriores** a ``hasta`` (todo si es ``None``)."""
    modulo = db.get(Modulo, modulo_id)
    if modulo is None:
        raise NoEncontrado("Módulo no encontrado")
    fundo = db.get(Fundo, modulo.fundo_id)
    turnos = {t.id: t for t in repo_riego.turnos_de_modulo(db, modulo_id)}
    texto_fundo = ambiente_service.nombre_fundo(fundo)

    filas: list[dict] = []
    con_registro: set[tuple[int, dt.date]] = set()
    for registro in repo_riego.vigentes(db, modulo_id, hasta=hasta):
        con_registro.add((registro.turno_id, registro.fecha))
        if registro.sin_riego:
            continue
        codigo = turnos[registro.turno_id].codigo
        for ciclo in registro.ciclos:
            filas.append({
                "fecha": registro.fecha, "turno": codigo, "valvula": ciclo.valvula,
                "inicio_min": ciclo.inicio_min, "fin_min": ciclo.fin_min,
                "hora_inicio": ciclo.hora_inicio, "hora_fin": ciclo.hora_fin,
                "fin_dia_siguiente": ciclo.fin_dia_siguiente, "duracion_min": ciclo.duracion_min,
                "riego_m3": ciclo.riego_m3, "riego_m3ha": ciclo.riego_m3ha, "area_ha": ciclo.area_ha,
            })

    desde_cronograma: set[tuple[dt.date, str]] = set()
    if hasta is not None:
        for ciclo in repo_riego.ciclos_cronograma_referencia(db, modulo_id, hasta):
            turno = turnos.get(ciclo.turno_id)
            if turno is None or (ciclo.turno_id, ciclo.fecha) in con_registro:
                continue
            desde_cronograma.add((ciclo.fecha, turno.codigo))
            area = (ciclo.riego_m3 / ciclo.riego_m3ha) if ciclo.riego_m3ha else turno.area_ha
            filas.append({
                "fecha": ciclo.fecha, "turno": turno.codigo, "valvula": turno.valvula_controlador,
                "inicio_min": ciclo.inicio_min, "fin_min": ciclo.fin_min,
                "hora_inicio": ciclo.hora_inicio, "hora_fin": ciclo.hora_fin,
                "fin_dia_siguiente": ciclo.fin_dia_siguiente, "duracion_min": ciclo.duracion_min,
                "riego_m3": ciclo.riego_m3, "riego_m3ha": ciclo.riego_m3ha, "area_ha": area,
            })

    riego = ciclos_dataframe(filas, texto_fundo, modulo.codigo)
    ciclos, descartados, diagnostico = limpiar_ciclos(riego, min_duracion_min, min_riego_m3ha)
    ambiente = ambiente_service.ambiente_para_modelo(db, fundo, hasta=hasta)
    historial = Historial(ciclos, tabla_turno_dia(ciclos), ambiente, descartados, diagnostico)
    return HistorialBD(historial, sorted(desde_cronograma))
