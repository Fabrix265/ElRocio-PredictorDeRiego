"""Riego **real** del controlador Galileo (Fabric) -> ``riego_registro`` aplicado, origen ``controlador``.

El cronograma publicado deja un riego **provisional** (lo que se planificó regar). Cuando llega el
dato del controlador para ese turno-día se crea una versión nueva **aplicada** que pasa a ser la
vigente; la provisional queda guardada como versión anterior (``basado_en_id``), así que el plan
y lo realmente regado se pueden comparar siempre (reporte de agua y versiones del turno-día).

Reglas:

- Reemplaza al provisional del cronograma y a lo cargado antes por histórico, Excel o el propio
  controlador (si el contenido cambió). Si el contenido es igual, no crea versión.
- **No** reemplaza lo registrado a mano (``origen = manual``): alguien lo decidió así; se avisa.
- Un turno sin filas del controlador en un día no se toca (falta de dato no es "no se regó").
- Solo días cerrados (hasta ayer, hora de Lima).
- Hace ``flush``; el commit lo hace quien llama.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Turno
from app.models.enums import EstadoRiego, OrigenRiego
from app.repositories import cronogramas as repo_cronogramas
from app.repositories import riego as repo
from app.repositories.datos_campo import ConteoUpsert
from app.services.riego_contenido import hash_contenido
from app.services.riego_service import _crear_registro

MOTIVO = "Riego real del controlador Galileo"


@dataclass
class ResultadoRiegoReal:
    conteo: ConteoUpsert = field(default_factory=ConteoUpsert)
    reemplazos_provisional: int = 0
    avisos: list[str] = field(default_factory=list)


def turnos_activos(db: Session) -> list[Turno]:
    return list(db.scalars(select(Turno).where(Turno.activo.is_(True)).order_by(Turno.modulo_id, Turno.orden)))


def aplicar(db: Session, grupos: dict[tuple[int, dt.date], list[dict[str, Any]]], *,
            hasta: dt.date) -> ResultadoRiegoReal:
    """Guarda los ciclos reales de cada ``(turno_id, fecha)`` con ``fecha <= hasta``."""
    r = ResultadoRiegoReal()
    turnos = {t.id: t for t in db.scalars(select(Turno).where(Turno.id.in_({t for t, _ in grupos})))}
    # Mismo orden de candados que F4: primero el cronograma del día, luego los turno-día por turno.
    for (turno_id, fecha) in sorted(grupos, key=lambda k: (k[1], turnos[k[0]].modulo_id, k[0])):
        if fecha > hasta:
            continue
        turno = turnos[turno_id]
        ciclos = grupos[(turno_id, fecha)]
        crono = repo_cronogramas.por_fecha(db, turno.modulo_id, fecha)
        if crono is not None:
            repo_cronogramas.obtener(db, crono.id, bloquear=True)
        vigente = repo.bloquear_turno_dia(db, turno.id, fecha)
        if vigente is not None and vigente.origen == OrigenRiego.manual:
            r.avisos.append(f"{turno.codigo} {fecha.isoformat()}: registrado a mano; se conservó")
            r.conteo = r.conteo.sumar(ConteoUpsert(omitidas=1))
            continue
        if (vigente is not None and vigente.estado == EstadoRiego.aplicado and not vigente.sin_riego
                and vigente.contenido_sha256 == hash_contenido(ciclos)):
            r.conteo = r.conteo.sumar(ConteoUpsert(omitidas=1))
            continue
        _crear_registro(db, turno=turno, fecha=fecha, vigente=vigente, ciclos=ciclos,
                        estado=EstadoRiego.aplicado, origen=OrigenRiego.controlador, actor=None,
                        motivo=MOTIVO)
        if vigente is None:
            r.conteo = r.conteo.sumar(ConteoUpsert(nuevas=1))
        else:
            r.conteo = r.conteo.sumar(ConteoUpsert(actualizadas=1))
            if vigente.estado == EstadoRiego.provisional:
                r.reemplazos_provisional += 1
    db.flush()
    return r
