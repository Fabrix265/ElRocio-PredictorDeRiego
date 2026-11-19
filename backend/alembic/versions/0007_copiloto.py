"""Copiloto agrónomo: tokens de servicio del agente y sugerencias pendientes de aprobación.

- ``token_servicio``: credencial del agente automático (n8n). Solo el SHA-256 del token.
- ``copiloto_sugerencia``: propuestas del agente que un encargado o admin aprueba o descarta.
  ``updated_at`` por trigger.

Ambas con RLS, GRANT a ``riego_app`` y nada para PUBLIC/anon/authenticated (``preparar_tabla``).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.migraciones import preparar_tabla

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESQUEMA = "riego"

# Congelados en esta migración (los del modelo pueden crecer con una migración nueva).
TIPOS = ("revisar_equipo", "revisar_datos", "regenerar_plan", "ajustar_riego", "otro")
ESTADOS = ("pendiente", "aprobada", "descartada")


def _en(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


def upgrade() -> None:
    op.create_table(
        "token_servicio",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("nombre", sa.String(length=60), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("prefijo", sa.String(length=16), nullable=False),
        sa.Column("activo", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("creado_por", sa.BigInteger(), nullable=True),
        sa.Column("ultimo_uso_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["creado_por"], ["riego.usuario.id"], ondelete="SET NULL",
                                name=op.f("fk_token_servicio_creado_por_usuario")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_token_servicio")),
        sa.UniqueConstraint("nombre", name=op.f("uq_token_servicio_nombre")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_token_servicio_token_hash")),
        schema=ESQUEMA,
    )
    op.create_index(op.f("ix_token_servicio_creado_por"), "token_servicio", ["creado_por"],
                    unique=False, schema=ESQUEMA)
    preparar_tabla("token_servicio", modo="crud")

    op.create_table(
        "copiloto_sugerencia",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("modulo_id", sa.BigInteger(), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("turno_id", sa.BigInteger(), nullable=True),
        sa.Column("tipo", sa.String(length=30), nullable=False),
        sa.Column("alerta_codigo", sa.String(length=40), nullable=True),
        sa.Column("titulo", sa.String(length=160), nullable=False),
        sa.Column("detalle", sa.Text(), nullable=True),
        sa.Column("estado", sa.String(length=20), server_default=sa.text("'pendiente'"), nullable=False),
        sa.Column("token_id", sa.BigInteger(), nullable=True),
        sa.Column("resuelto_por", sa.BigInteger(), nullable=True),
        sa.Column("resuelto_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comentario_resolucion", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(f"tipo IN ({_en(TIPOS)})", name=op.f("ck_copiloto_sugerencia_tipo")),
        sa.CheckConstraint(f"estado IN ({_en(ESTADOS)})", name=op.f("ck_copiloto_sugerencia_estado")),
        sa.ForeignKeyConstraint(["modulo_id"], ["riego.modulo.id"],
                                name=op.f("fk_copiloto_sugerencia_modulo_id_modulo")),
        sa.ForeignKeyConstraint(["turno_id"], ["riego.turno.id"],
                                name=op.f("fk_copiloto_sugerencia_turno_id_turno")),
        sa.ForeignKeyConstraint(["token_id"], ["riego.token_servicio.id"], ondelete="SET NULL",
                                name=op.f("fk_copiloto_sugerencia_token_id_token_servicio")),
        sa.ForeignKeyConstraint(["resuelto_por"], ["riego.usuario.id"], ondelete="SET NULL",
                                name=op.f("fk_copiloto_sugerencia_resuelto_por_usuario")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_copiloto_sugerencia")),
        schema=ESQUEMA,
    )
    for columna in ("modulo_id", "turno_id", "token_id", "resuelto_por"):
        op.create_index(op.f(f"ix_copiloto_sugerencia_{columna}"), "copiloto_sugerencia", [columna],
                        unique=False, schema=ESQUEMA)
    op.create_index("ix_copiloto_sugerencia_estado_modulo_id_fecha", "copiloto_sugerencia",
                    ["estado", "modulo_id", "fecha"], unique=False, schema=ESQUEMA)
    # Una sola pendiente por propuesta (n8n manda varias en paralelo; el agente puede repetirlas).
    op.create_index("uq_copiloto_sugerencia_pendiente", "copiloto_sugerencia",
                    ["modulo_id", "fecha", "tipo", "turno_id", "alerta_codigo", sa.text("lower(titulo)")],
                    unique=True, schema=ESQUEMA, postgresql_nulls_not_distinct=True,
                    postgresql_where=sa.text("estado = 'pendiente'"))
    preparar_tabla("copiloto_sugerencia", modo="crud")
    op.execute(f"CREATE TRIGGER tg_copiloto_sugerencia_updated_at BEFORE UPDATE ON {ESQUEMA}.copiloto_sugerencia "
               f"FOR EACH ROW EXECUTE FUNCTION {ESQUEMA}.fijar_updated_at()")


def downgrade() -> None:
    op.drop_table("copiloto_sugerencia", schema=ESQUEMA)
    op.drop_table("token_servicio", schema=ESQUEMA)
