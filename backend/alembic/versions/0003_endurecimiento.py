"""Endurecimiento tras la revisión de F1.

1. ``tipo_intento`` suma ``cambiar_password`` (límite de intentos de la contraseña actual).
2. ``sesion_refresh.gracia_usada_at``: la gracia de 30 s del refresh se usa una sola vez por token.
3. ``riego_registro`` (historial de versiones, §2.2): ``riego_app`` ya no puede borrar ni reescribir
   versiones; solo marcar ``vigente`` de true a false (lo exige también un trigger, incluso para el
   dueño).
4. ``updated_at`` lo fija un trigger de la BD (``riego.fijar_updated_at``): también en upserts
   (``ON CONFLICT DO UPDATE``) y UPDATE en SQL directo, que no aplican el ``onupdate`` del ORM.

El valor ``cambiar_password`` del enum no se quita en el downgrade (Postgres no permite borrar
valores de un enum); ``ADD VALUE IF NOT EXISTS`` permite volver a subir.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.migraciones import preparar_funcion

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESQUEMA = "riego"
ROL_APP = "riego_app"

TABLAS_UPDATED_AT = (
    "usuario", "cronograma", "meteo_lectura", "phytech_suelo_horario", "phytech_planta_diario",
    "ambiente_diario",
)


def upgrade() -> None:
    # 1) Nuevo tipo de intento (no se usa en esta misma transacción).
    op.execute(f"ALTER TYPE {ESQUEMA}.tipo_intento ADD VALUE IF NOT EXISTS 'cambiar_password'")

    # 2) Gracia del refresh: una sola emisión por token reemplazado.
    op.add_column(
        "sesion_refresh",
        sa.Column("gracia_usada_at", sa.DateTime(timezone=True), nullable=True),
        schema=ESQUEMA,
    )

    # 3) riego_registro: versiones inmutables salvo dejar de ser vigentes.
    # Revocar el UPDATE de tabla también quita los de columna; luego solo UPDATE(vigente).
    op.execute(f"REVOKE UPDATE, DELETE ON {ESQUEMA}.riego_registro FROM {ROL_APP}")
    op.execute(f"GRANT UPDATE (vigente) ON {ESQUEMA}.riego_registro TO {ROL_APP}")
    op.execute(
        f"""
        CREATE FUNCTION {ESQUEMA}.riego_registro_inmutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Los registros de riego no se borran: editar crea una versión nueva'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF NOT (OLD.vigente AND NOT NEW.vigente) THEN
                RAISE EXCEPTION 'Solo se puede marcar una versión de riego como no vigente'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF (to_jsonb(NEW) - 'vigente') IS DISTINCT FROM (to_jsonb(OLD) - 'vigente') THEN
                RAISE EXCEPTION 'La versión de riego % es inmutable (solo deja de ser vigente)', OLD.id
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER tg_riego_registro_inmutable BEFORE UPDATE OR DELETE "
        f"ON {ESQUEMA}.riego_registro FOR EACH ROW "
        f"EXECUTE FUNCTION {ESQUEMA}.riego_registro_inmutable()"
    )
    preparar_funcion("riego_registro_inmutable()")

    # 4) updated_at mantenido por la BD.
    op.execute(
        f"""
        CREATE FUNCTION {ESQUEMA}.fijar_updated_at() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END;
        $$
        """
    )
    for tabla in TABLAS_UPDATED_AT:
        op.execute(
            f"CREATE TRIGGER tg_{tabla}_updated_at BEFORE UPDATE ON {ESQUEMA}.{tabla} "
            f"FOR EACH ROW EXECUTE FUNCTION {ESQUEMA}.fijar_updated_at()"
        )
    preparar_funcion("fijar_updated_at()")


def downgrade() -> None:
    for tabla in TABLAS_UPDATED_AT:
        op.execute(f"DROP TRIGGER IF EXISTS tg_{tabla}_updated_at ON {ESQUEMA}.{tabla}")
    op.execute(f"DROP FUNCTION IF EXISTS {ESQUEMA}.fijar_updated_at()")

    op.execute(f"DROP TRIGGER IF EXISTS tg_riego_registro_inmutable ON {ESQUEMA}.riego_registro")
    op.execute(f"DROP FUNCTION IF EXISTS {ESQUEMA}.riego_registro_inmutable()")
    op.execute(f"REVOKE UPDATE ON {ESQUEMA}.riego_registro FROM {ROL_APP}")
    op.execute(f"GRANT UPDATE, DELETE ON {ESQUEMA}.riego_registro TO {ROL_APP}")

    op.drop_column("sesion_refresh", "gracia_usada_at", schema=ESQUEMA)
