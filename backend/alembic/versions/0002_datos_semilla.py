"""Datos semilla: empresas, fundo ENSUEÑO 1, módulo EN01-MOD5, turnos, lotes y motivos.

Fuente: hoja ``siga`` (no está en git). Idempotente (``ON CONFLICT DO NOTHING``): correrla otra
vez no duplica ni modifica filas existentes.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CAMPANA = "2026-2027"

EMPRESAS = (
    ("AVOPERU", "AVO PERÚ S.A.C."),
    ("TALSA", "Talsa"),  # sin fundos por ahora (decisión D5)
)

# Ñ precompuesta (U+00D1, Unicode NFC): debe coincidir con el texto de riego_ml.
FUNDO = {"codigo": "EN01", "nombre": "ENSUEÑO 1", "zona": "CHAO", "empresa": "AVOPERU"}

MODULO = {
    "codigo": "EN01-MOD5",
    "nombre": "ENSUEÑO 1 MODULO 5",
    "area_ha": 62.8292,
    "cultivo": "PALTA",
    "variedad": "HASS",
    "campana": CAMPANA,
}

# (codigo, orden, area_ha, valvula_controlador, valvula_siga)
TURNOS = (
    ("TE01", 1, 13.019, "6061000", "60610002"),
    ("TE02", 2, 12.649, "6263000", "62630002"),
    ("TE03", 3, 12.423, "6465000", "64650002"),
    ("TE04", 4, 12.459, "6667000", "66670002"),
    ("TE05", 5, 12.2792, "6869000", "68690002"),
)

# turno -> [(lote, area_ha)]
LOTES = {
    "TE01": (("E001", 3.049), ("E002", 3.0884), ("E003", 3.1688), ("E004", 1.8564),
             ("E005A", 0.6123), ("E005B", 1.2441)),
    "TE02": (("E006", 3.143), ("E007", 3.143), ("E008", 3.1815), ("E009", 3.1815)),
    "TE03": (("E010", 3.0966), ("E011", 3.0966), ("E012", 3.1149), ("E013", 3.1149)),
    "TE04": (("E014", 3.122), ("E015", 3.122), ("E016", 3.1075), ("E017", 3.1075)),
    "TE05": (("E018", 3.1107), ("E019", 3.1107), ("E020", 2.3808), ("E021", 3.677)),
}

# (codigo, nombre, orden)
MOTIVOS = (
    ("clima_lluvia", "Clima / lluvia", 1),
    ("criterio_agronomico", "Criterio agronómico", 2),
    ("programa_semanal", "Programa semanal", 3),
    ("falla_equipo", "Falla de equipo", 4),
    ("operacion_personal", "Operación / personal", 5),
    ("otro", "Otro", 6),
)


def sentencias() -> list[tuple[str, dict]]:
    """Sentencias idempotentes de la semilla (las usa también el test de idempotencia)."""
    s: list[tuple[str, dict]] = []
    for codigo, nombre in EMPRESAS:
        s.append((
            "INSERT INTO riego.empresa (codigo, nombre) VALUES (:codigo, :nombre) "
            "ON CONFLICT DO NOTHING",
            {"codigo": codigo, "nombre": nombre},
        ))
    s.append((
        "INSERT INTO riego.fundo (empresa_id, codigo, nombre, zona) "
        "SELECT e.id, :codigo, :nombre, :zona FROM riego.empresa e WHERE e.codigo = :empresa "
        "ON CONFLICT DO NOTHING",
        FUNDO,
    ))
    s.append((
        "INSERT INTO riego.modulo (fundo_id, codigo, nombre, area_ha, cultivo, variedad, campana) "
        "SELECT f.id, :codigo, :nombre, :area_ha, :cultivo, :variedad, :campana "
        "FROM riego.fundo f WHERE f.codigo = :fundo ON CONFLICT DO NOTHING",
        {**MODULO, "fundo": FUNDO["codigo"]},
    ))
    for codigo, orden, area, valvula, siga in TURNOS:
        s.append((
            "INSERT INTO riego.turno "
            "(modulo_id, codigo, orden, area_ha, valvula_controlador, valvula_siga) "
            "SELECT m.id, :codigo, :orden, :area_ha, :valvula, :siga "
            "FROM riego.modulo m WHERE m.codigo = :modulo ON CONFLICT DO NOTHING",
            {"codigo": codigo, "orden": orden, "area_ha": area, "valvula": valvula,
             "siga": siga, "modulo": MODULO["codigo"]},
        ))
    for turno, lotes in LOTES.items():
        for codigo, area in lotes:
            s.append((
                "INSERT INTO riego.lote (turno_id, codigo, area_ha, campana) "
                "SELECT t.id, :codigo, :area_ha, :campana FROM riego.turno t "
                "JOIN riego.modulo m ON m.id = t.modulo_id "
                "WHERE m.codigo = :modulo AND t.codigo = :turno ON CONFLICT DO NOTHING",
                {"codigo": codigo, "area_ha": area, "campana": CAMPANA,
                 "modulo": MODULO["codigo"], "turno": turno},
            ))
    for codigo, nombre, orden in MOTIVOS:
        s.append((
            "INSERT INTO riego.motivo_correccion (codigo, nombre, orden) "
            "VALUES (:codigo, :nombre, :orden) ON CONFLICT DO NOTHING",
            {"codigo": codigo, "nombre": nombre, "orden": orden},
        ))
    return s


def upgrade() -> None:
    # op.execute + bindparams: en modo offline (``alembic upgrade head --sql``) Alembic escribe los
    # valores como literales; con ``bind.execute(text, params)`` los perdía y quedaban NULL.
    for sql, parametros in sentencias():
        op.execute(sa.text(sql).bindparams(**parametros))


def _borrar_codigos(tabla: str, codigos: list[str]) -> None:
    """``DELETE ... WHERE codigo IN (...)`` con parámetro expandible (literales en offline)."""
    op.execute(
        sa.text(f"DELETE FROM riego.{tabla} WHERE codigo IN :codigos").bindparams(
            sa.bindparam("codigos", codigos, expanding=True)
        )
    )


def downgrade() -> None:
    modulo = MODULO["codigo"]
    op.execute(
        sa.text(
            "DELETE FROM riego.lote l USING riego.turno t, riego.modulo m "
            "WHERE l.turno_id = t.id AND t.modulo_id = m.id AND m.codigo = :modulo"
        ).bindparams(modulo=modulo)
    )
    op.execute(
        sa.text(
            "DELETE FROM riego.turno t USING riego.modulo m "
            "WHERE t.modulo_id = m.id AND m.codigo = :modulo"
        ).bindparams(modulo=modulo)
    )
    _borrar_codigos("modulo", [modulo])
    _borrar_codigos("fundo", [FUNDO["codigo"]])
    _borrar_codigos("empresa", [codigo for codigo, _ in EMPRESAS])
    _borrar_codigos("motivo_correccion", [codigo for codigo, _, _ in MOTIVOS])
