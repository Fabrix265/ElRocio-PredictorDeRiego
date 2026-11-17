"""Filas de ``silver_galileo_consolas`` -> ciclos de riego por turno y día (formato ``riego_ciclo``).

Reglas (las dio El Rocío):

- **Turno:** se concatenan las columnas ``Valve A`` … ``Valve E`` (como enteros, sin decimales)
  y esa llave se busca en ``turno.valvula_controlador`` (p. ej. 66, 67, 0, 0, 0 -> ``6667000`` ->
  TE04). Las llaves que no son de ningún turno se cuentan y se ignoran (otras consolas o módulos).
- **Agua:** ``Water Done`` son los m³ totales del ciclo y ``Time Water Done`` los minutos; los
  m³/ha salen de dividir por la superficie del turno (``turno.area_ha``).
- **Hora:** en la tabla real, ``time`` trae día y hora de **inicio** del ciclo (verificado el
  2026-11-17: coincide minuto a minuto, en duración y en m³ con el histórico de TE04). También se
  aceptan columnas separadas ``fecha`` + ``Hora`` (formato del Excel).
- Solo filas de la consola del fundo (``FABRIC_CONSOLA``, por defecto ``GALENSUENO1``): otras
  consolas podrían repetir números de válvula.
- La tabla trae filas repetidas (el mismo registro en varias versiones del archivo de origen).
- Una fila = un ciclo. Las filas repetidas exactas se descartan; si dos filas distintas del mismo
  turno-día empiezan en el mismo minuto se queda la primera y se informa.
"""

from __future__ import annotations

import datetime as dt
import decimal
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

MINUTOS_DIA = 1440
# ``time`` / ``Hora`` es la hora de inicio del ciclo (verificado con el histórico).
HORA_ES_INICIO = True

# Nombre canónico -> nombres aceptados en la tabla (se comparan sin mayúsculas ni espacios extra).
# Columnas con "_" se comparan como si fueran espacios (``valve_a`` = ``Valve A``).
COLUMNAS: dict[str, tuple[str, ...]] = {
    "fecha": ("fecha", "date", "time"),
    "hora": ("hora", "hour", "time"),
    "valvula_a": ("valve a", "valvula a", "válvula a"),
    "valvula_b": ("valve b", "valvula b", "válvula b"),
    "valvula_c": ("valve c", "valvula c", "válvula c"),
    "valvula_d": ("valve d", "valvula d", "válvula d"),
    "valvula_e": ("valve e", "valvula e", "válvula e"),
    "m3": ("water done",),
    "minutos": ("time water done",),
}
VALVULAS = ("valvula_a", "valvula_b", "valvula_c", "valvula_d", "valvula_e")


class TurnoDestino(Protocol):
    id: int
    codigo: str
    area_ha: float
    valvula_controlador: str


def _norm(nombre: str) -> str:
    return " ".join(nombre.strip().lower().replace("_", " ").split())


def resolver_columnas(disponibles: Iterable[str]) -> dict[str, str]:
    """Canónico -> nombre real en la tabla. ``ValueError`` si falta alguna."""
    reales = {_norm(n): n for n in disponibles}
    resueltas, faltan = {}, []
    for canonico, alias in COLUMNAS.items():
        real = next((reales[a] for a in alias if a in reales), None)
        if real is None:
            faltan.append(alias[0])
        else:
            resueltas[canonico] = real
    if faltan:
        raise ValueError("Faltan columnas en la tabla del controlador: " + ", ".join(faltan))
    return resueltas


def _numero(valor: Any) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, str):
        texto = valor.strip().replace(",", ".")
        if not texto:
            return None
        try:
            valor = float(texto)
        except ValueError:
            return None
    try:
        numero = float(valor)
    except (TypeError, ValueError, decimal.InvalidOperation):
        return None
    return None if math.isnan(numero) or math.isinf(numero) else numero


def parte_llave(valor: Any) -> str:
    """Una válvula como texto de la llave: 66 / 66.0 / "66" -> ``66``; vacío o nulo -> ``0``."""
    numero = _numero(valor)
    if numero is None:
        return "0"
    return str(int(numero)) if float(numero).is_integer() else str(numero)


def llave(valores: Iterable[Any]) -> str:
    return "".join(parte_llave(v) for v in valores)


def fecha_de(valor: Any) -> dt.date | None:
    if valor is None:
        return None
    if isinstance(valor, dt.datetime):
        return valor.date()
    if isinstance(valor, dt.date):
        return valor
    texto = str(valor).strip()
    try:
        return dt.datetime.fromisoformat(texto).date()
    except ValueError:
        pass
    try:  # 7/10/2024 o 7/10/2024 00:00 (día/mes/año, como en Perú)
        return dt.datetime.strptime(texto.split()[0], "%d/%m/%Y").date()
    except (ValueError, IndexError):
        return None


def minutos_de(valor: Any) -> float | None:
    """Hora del día -> minutos desde las 00:00 (``time``, ``datetime``, ``timedelta``, "HH:MM[:SS]"
    o fracción de día de Excel)."""
    if valor is None:
        return None
    if isinstance(valor, dt.datetime):
        valor = valor.time()
    if isinstance(valor, dt.time):
        return valor.hour * 60 + valor.minute + valor.second / 60
    if isinstance(valor, dt.timedelta):
        minutos = valor.total_seconds() / 60
        return minutos if 0 <= minutos < MINUTOS_DIA else None
    if isinstance(valor, str):
        texto = valor.strip()
        if " " in texto or "T" in texto:  # "2026-11-05T05:01:00" (crudo JSON) o "1899-12-30 05:01:00"
            texto = texto.replace("T", " ").split()[-1]
        partes = texto.split(":")
        if 2 <= len(partes) <= 3 and all(p.replace(".", "", 1).isdigit() for p in partes):
            h, m = int(partes[0]), int(partes[1])
            s = float(partes[2]) if len(partes) == 3 else 0.0
            if 0 <= h < 24 and 0 <= m < 60:
                return h * 60 + m + s / 60
        return None
    numero = _numero(valor)
    if numero is not None and 0 <= numero < 1:  # fracción de día (Excel)
        return numero * MINUTOS_DIA
    return None


def hhmm(minuto: float) -> str:
    total = int(round(minuto)) % MINUTOS_DIA
    return f"{total // 60:02d}:{total % 60:02d}"


@dataclass
class ResultadoAdaptacion:
    # (turno_id, fecha) -> ciclos ordenados por inicio (formato riego_ciclo, sin registro_id)
    grupos: dict[tuple[int, dt.date], list[dict[str, Any]]] = field(default_factory=dict)
    filas: int = 0
    sin_turno: Counter = field(default_factory=Counter)  # llave -> filas
    invalidas: int = 0
    vacias: int = 0  # sin agua ni tiempo
    duplicadas: int = 0
    choques: list[str] = field(default_factory=list)

    def resumen(self) -> dict[str, Any]:
        return {
            "filas": self.filas, "turno_dias": len(self.grupos),
            "ciclos": sum(len(c) for c in self.grupos.values()),
            "llaves_sin_turno": dict(self.sin_turno.most_common(20)),
            "filas_invalidas": self.invalidas, "filas_sin_agua": self.vacias,
            "filas_duplicadas": self.duplicadas, "choques": self.choques[:20],
        }


def adaptar(filas: Iterable[Mapping[str, Any]], columnas: Mapping[str, str],
            turnos: Iterable[TurnoDestino]) -> ResultadoAdaptacion:
    """Agrupa las filas crudas (dicts con los nombres reales de la tabla) en ciclos por turno-día."""
    por_llave = {str(t.valvula_controlador).strip(): t for t in turnos}
    r = ResultadoAdaptacion()
    vistos: set[tuple] = set()
    for fila in filas:
        r.filas += 1
        clave_llave = llave(fila.get(columnas[v]) for v in VALVULAS)
        turno = por_llave.get(clave_llave)
        if turno is None:
            r.sin_turno[clave_llave] += 1
            continue
        fecha = fecha_de(fila.get(columnas["fecha"]))
        hora = minutos_de(fila.get(columnas["hora"]))
        m3 = _numero(fila.get(columnas["m3"]))
        minutos = _numero(fila.get(columnas["minutos"]))
        if fecha is None or hora is None or m3 is None or minutos is None or m3 < 0 or minutos < 0:
            r.invalidas += 1
            continue
        if m3 == 0 and minutos == 0:
            r.vacias += 1
            continue
        if minutos > MINUTOS_DIA:
            r.invalidas += 1
            continue
        inicio = round(hora if HORA_ES_INICIO else hora - minutos, 1)
        if inicio < 0:  # terminó después de medianoche: el ciclo empezó el día anterior
            inicio = round(inicio + MINUTOS_DIA, 1)
            fecha -= dt.timedelta(days=1)
        duracion = round(minutos, 2)  # como el histórico (no redondear más: cambiaría el hash)
        firma = (turno.id, fecha, inicio, duracion, round(m3, 3))
        if firma in vistos:
            r.duplicadas += 1
            continue
        vistos.add(firma)
        ciclos = r.grupos.setdefault((turno.id, fecha), [])
        if any(c["inicio_min"] == inicio for c in ciclos):
            r.choques.append(f"{turno.codigo} {fecha.isoformat()} {hhmm(inicio)}: dos ciclos con el mismo inicio")
            continue
        fin = round(inicio + duracion, 2)
        area = float(turno.area_ha)
        ciclos.append({
            "inicio_min": inicio, "fin_min": fin, "duracion_min": duracion,
            "riego_m3": round(m3, 3), "riego_m3ha": m3 / area if area > 0 else None,
            "area_ha": area, "valvula": clave_llave, "hora_inicio": hhmm(inicio), "hora_fin": hhmm(fin),
            "fin_dia_siguiente": fin >= MINUTOS_DIA,
        })
    for ciclos in r.grupos.values():
        ciclos.sort(key=lambda c: c["inicio_min"])
    return r


def a_json(valor: Any) -> Any:
    """Valor de una fila cruda en algo que se puede guardar en JSONB (``ingesta_crudo``)."""
    if isinstance(valor, (dt.datetime, dt.date, dt.time)):
        return valor.isoformat()
    if isinstance(valor, dt.timedelta):
        return valor.total_seconds()
    if isinstance(valor, decimal.Decimal):
        return float(valor)
    if isinstance(valor, float) and (math.isnan(valor) or math.isinf(valor)):
        return None
    if isinstance(valor, (bytes, bytearray)):
        return valor.hex()
    return valor
