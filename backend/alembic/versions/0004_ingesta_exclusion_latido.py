"""Ingesta: una sola corrida en curso por fuente y latido de las corridas (revisión de F2).

1. ``ingesta_corrida.latido_at``: el proceso que ejecuta una corrida lo actualiza cada minuto en
   una transacción aparte. Una corrida ``en_curso`` sin latido reciente quedó sin dueño (el
   proceso murió o no pudo guardar) y se cierra como interrumpida en minutos, no en horas.
2. Índice único parcial ``uq_ingesta_corrida_en_curso (fuente) WHERE estado = 'en_curso'``: dos
   "Actualizar ahora" simultáneos, o uno manual y la tarea programada, no pueden ejecutar la misma
   fuente en paralelo (sin candados de sesión: sirve con el pooler). Antes de crearlo se cierran
   como interrumpidas las corridas en curso repetidas (queda la más reciente de cada fuente).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESQUEMA = "riego"


def upgrade() -> None:
    op.add_column(
        "ingesta_corrida",
        sa.Column("latido_at", sa.DateTime(timezone=True), nullable=True),
        schema=ESQUEMA,
    )
    op.execute(
        f"""
        UPDATE {ESQUEMA}.ingesta_corrida AS c
           SET estado = 'error', fin_at = now(),
               errores = '[{{"tipo": "interrumpida", "status_code": null, "endpoint": null,
                            "mensaje": "Corrida en curso repetida de la misma fuente"}}]'::jsonb
         WHERE c.estado = 'en_curso'
           AND EXISTS (SELECT 1 FROM {ESQUEMA}.ingesta_corrida AS o
                        WHERE o.fuente = c.fuente AND o.estado = 'en_curso'
                          AND (o.inicio_at, o.id) > (c.inicio_at, c.id))
        """
    )
    op.create_index(
        "uq_ingesta_corrida_en_curso", "ingesta_corrida", ["fuente"], unique=True,
        schema=ESQUEMA, postgresql_where=sa.text("estado = 'en_curso'"),
    )


def downgrade() -> None:
    op.drop_index("uq_ingesta_corrida_en_curso", table_name="ingesta_corrida", schema=ESQUEMA)
    op.drop_column("ingesta_corrida", "latido_at", schema=ESQUEMA)
