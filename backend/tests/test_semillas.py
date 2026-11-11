"""Datos semilla de la migración 0002."""

from __future__ import annotations

import importlib.util
import unicodedata
from pathlib import Path

from sqlalchemy import Connection, select, text
from sqlalchemy.orm import Session

from app.models import Empresa, Fundo, Lote, Modulo, MotivoCorreccion, Turno

MIGRACION = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0002_datos_semilla.py"


def _modulo_semilla():
    spec = importlib.util.spec_from_file_location("semilla_0002", MIGRACION)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_empresas(db: Session):
    empresas = {e.codigo: e.nombre for e in db.scalars(select(Empresa))}
    assert empresas == {"AVOPERU": "AVO PERÚ S.A.C.", "TALSA": "Talsa"}


def test_fundo_ensueno_en_nfc(db: Session):
    fundo = db.scalars(select(Fundo)).one()
    assert (fundo.codigo, fundo.zona) == ("EN01", "CHAO")
    assert fundo.nombre == "ENSUEÑO 1"
    assert unicodedata.is_normalized("NFC", fundo.nombre)
    assert len(fundo.nombre) == 9  # Ñ precompuesta, no N + tilde combinante
    assert fundo.empresa.codigo == "AVOPERU"


def test_modulo_y_turnos(db: Session):
    modulo = db.scalars(select(Modulo)).one()
    assert (modulo.codigo, modulo.nombre) == ("EN01-MOD5", "ENSUEÑO 1 MODULO 5")
    assert modulo.area_ha == 62.8292
    assert (modulo.cultivo, modulo.variedad, modulo.campana) == ("PALTA", "HASS", "2026-2027")
    turnos = [
        (t.codigo, t.orden, t.area_ha, t.valvula_controlador, t.valvula_siga) for t in modulo.turnos
    ]
    assert turnos == [
        ("TE01", 1, 13.019, "6061000", "60610002"),
        ("TE02", 2, 12.649, "6263000", "62630002"),
        ("TE03", 3, 12.423, "6465000", "64650002"),
        ("TE04", 4, 12.459, "6667000", "66670002"),
        ("TE05", 5, 12.2792, "6869000", "68690002"),
    ]


def test_lotes(db: Session):
    filas = db.execute(
        select(Turno.codigo, Lote.codigo, Lote.area_ha, Lote.campana).join(Lote.turno)
        .order_by(Lote.codigo)
    ).all()
    assert len(filas) == 22  # E001..E021 con E005 dividido en E005A y E005B
    assert {f[3] for f in filas} == {"2026-2027"}
    por_turno: dict[str, list[str]] = {}
    for turno, lote, _area, _campana in filas:
        por_turno.setdefault(turno, []).append(lote)
    assert por_turno["TE01"] == ["E001", "E002", "E003", "E004", "E005A", "E005B"]
    assert por_turno["TE05"] == ["E018", "E019", "E020", "E021"]
    areas = {lote: area for _t, lote, area, _c in filas}
    assert areas["E005A"] == 0.6123 and areas["E021"] == 3.677


def test_motivos(db: Session):
    motivos = [
        (m.codigo, m.nombre, m.orden)
        for m in db.scalars(select(MotivoCorreccion).order_by(MotivoCorreccion.orden))
    ]
    assert motivos == [
        ("clima_lluvia", "Clima / lluvia", 1),
        ("criterio_agronomico", "Criterio agronómico", 2),
        ("programa_semanal", "Programa semanal", 3),
        ("falla_equipo", "Falla de equipo", 4),
        ("operacion_personal", "Operación / personal", 5),
        ("otro", "Otro", 6),
    ]


def test_semilla_idempotente(conexion: Connection):
    tablas = ("empresa", "fundo", "modulo", "turno", "lote", "motivo_correccion")

    def conteos() -> dict[str, int]:
        return {t: conexion.execute(text(f"SELECT count(*) FROM riego.{t}")).scalar() for t in tablas}

    antes = conteos()
    for sql, parametros in _modulo_semilla().sentencias():
        conexion.execute(text(sql), parametros)
    assert conteos() == antes
