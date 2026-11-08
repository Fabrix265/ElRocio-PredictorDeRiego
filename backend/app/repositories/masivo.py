"""Escrituras masivas con ``INSERT … SELECT * FROM unnest(arreglos)``.

Un ``INSERT … VALUES`` de miles de filas lleva miles de parámetros: psycopg no cachea sentencias
largas y vuelve a convertir los marcadores en cada lote (≈0,5 s por cada 1000 filas). Con
``unnest`` cada columna viaja como **un** arreglo tipado: la sentencia es corta y cada lote es un
solo viaje a la BD.

Solo para columnas escalares (números, textos, fechas, booleanos, enums); las ``jsonb`` usan el
camino normal (``admite_unnest``).
"""

from __future__ import annotations

import enum
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Enum, Table, Text, bindparam, cast, func, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, Insert, insert

LOTE = 5000


def admite_unnest(tabla: Table, columnas: Sequence[str]) -> bool:
    return not any(isinstance(tabla.c[c].type, JSONB) for c in columnas)


def insert_unnest(tabla: Table, columnas: Sequence[str]) -> Insert:
    """``INSERT INTO tabla (columnas) SELECT … FROM unnest(CAST(:p_<col> AS tipo[]), …)``.

    Los parámetros ``p_<col>`` (una lista por columna) se arman con :func:`parametros`. Los enums
    viajan como texto y se convierten en el SELECT.
    """
    arreglos = []
    for columna in columnas:
        tipo = tabla.c[columna].type
        tipo_arreglo = ARRAY(Text()) if isinstance(tipo, Enum) else ARRAY(tipo)
        arreglos.append(cast(bindparam(f"p_{columna}", type_=tipo_arreglo), tipo_arreglo))
    origen = func.unnest(*arreglos).table_valued(*columnas).render_derived(name="u")
    seleccion = select(*[
        cast(origen.c[c], tabla.c[c].type) if isinstance(tabla.c[c].type, Enum) else origen.c[c]
        for c in columnas
    ])
    return insert(tabla).from_select(list(columnas), seleccion)


def _valor(valor: Any) -> Any:
    return valor.value if isinstance(valor, enum.Enum) else valor


def parametros(columnas: Sequence[str], filas: Sequence[dict[str, Any]]) -> dict[str, list]:
    return {f"p_{c}": [_valor(f.get(c)) for f in filas] for c in columnas}
