"""Contenido de un turno-día de riego: ciclos normalizados y su hash.

Lo usan la carga histórica, la carga de Excel (§3.5) y la edición manual: dos registros con el
mismo contenido tienen el mismo ``contenido_sha256`` (subir otra vez el mismo archivo da "igual").

Los ciclos llegan de ``riego_ml`` (``leer_riego`` + ``limpiar_ciclos``, columnas
``COLUMNAS_RIEGO``) y se guardan en ``riego_ciclo`` con :func:`ciclos_para_bd`.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

# Campos que definen el contenido (lo demás se deriva de ellos) y sus decimales en el hash.
CAMPOS_HASH: dict[str, int | None] = {
    "inicio_min": 4,
    "duracion_min": 4,
    "riego_m3": 4,
    "riego_m3ha": 6,
    "valvula": None,
}


def texto_valvula(valor: Any) -> str | None:
    """Válvula como texto (``6061000``; los números de Excel pueden venir como 6061000.0)."""
    if valor is None or (isinstance(valor, float) and math.isnan(valor)) or valor is pd.NA:
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor).strip()
    return texto[:20] or None


def _numero(valor: Any) -> float | None:
    if valor is None or valor is pd.NA:
        return None
    numero = float(valor)
    return None if math.isnan(numero) else numero


def ciclos_para_bd(ciclos: pd.DataFrame | Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Ciclos de un turno-día (formato ``COLUMNAS_RIEGO``, DataFrame o lista de dicts) -> filas
    de ``riego_ciclo`` (sin ``registro_id``), ordenadas por inicio."""
    registros = ciclos.to_dict("records") if isinstance(ciclos, pd.DataFrame) else list(ciclos)
    filas = []
    for fila in sorted(registros, key=lambda r: float(r["inicio_min"])):
        filas.append({
            "inicio_min": float(fila["inicio_min"]),
            "fin_min": float(fila["fin_min"]),
            "duracion_min": float(fila["duracion_min"]),
            "riego_m3": _numero(fila["riego_m3"]),
            "riego_m3ha": _numero(fila["riego_m3ha"]),
            "area_ha": _numero(fila["area_ha"]),
            "valvula": texto_valvula(fila["Valvula"]),
            "hora_inicio": str(fila["hora_inicio"]),
            "hora_fin": str(fila["hora_fin"]),
            "fin_dia_siguiente": bool(fila["fin_dia_siguiente"]),
        })
    return filas


def hash_contenido(ciclos: Iterable[Mapping[str, Any]], sin_riego: bool = False) -> str:
    """SHA-256 del contenido canónico (ciclos ordenados por inicio, valores redondeados)."""
    canonicos = []
    for ciclo in ciclos:
        canonico = {}
        for campo, decimales in CAMPOS_HASH.items():
            valor = ciclo.get(campo)
            if decimales is not None:
                valor = _numero(valor)
                valor = None if valor is None else round(valor, decimales)
            canonico[campo] = valor
        canonicos.append(canonico)
    canonicos.sort(key=lambda c: (c["inicio_min"] is None, c["inicio_min"] or 0))
    texto = json.dumps({"sin_riego": bool(sin_riego), "ciclos": canonicos}, sort_keys=True,
                       separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()
