"""Anulación y borrado de cronogramas nunca publicados.

Las dependencias mantienen SELECT/INSERT para riego_app. Solo las cascadas de un
borrado permitido pueden retirar versiones, turnos, ciclos y eventos. Las demás
FK conservan NO ACTION: una referencia externa impide el borrado completo.

El downgrade rechaza fechas duplicadas para evitar perder historial. El valor
anulado del enum permanece (PostgreSQL no permite quitar valores).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.migraciones import preparar_funcion

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESQUEMA = "riego"
DEPENDENCIAS = (
    ("cronograma_version", "cronograma_id", "cronograma"),
    ("cronograma_evento", "cronograma_id", "cronograma"),
    ("cronograma_turno", "version_id", "cronograma_version"),
    ("cronograma_ciclo", "version_id", "cronograma_version"),
)


def _claves(*, cascada: bool) -> None:
    for tabla, columna, padre in DEPENDENCIAS:
        nombre = f"fk_{tabla}_{columna}_{padre}"
        op.drop_constraint(nombre, tabla, schema=ESQUEMA, type_="foreignkey")
        op.create_foreign_key(nombre, tabla, padre, [columna], ["id"],
                              source_schema=ESQUEMA, referent_schema=ESQUEMA,
                              ondelete="CASCADE" if cascada else None)


def _triggers(*, cascada: bool) -> None:
    for tabla, _, _ in DEPENDENCIAS:
        funcion = "cronograma_dependencia_inmutable" if cascada else (
            "cronograma_version_inmutable" if tabla == "cronograma_version" else "rechazar_modificacion"
        )
        op.execute(f"DROP TRIGGER tg_{tabla}_inmutable ON {ESQUEMA}.{tabla}")
        op.execute(f"CREATE TRIGGER tg_{tabla}_inmutable BEFORE UPDATE OR DELETE ON {ESQUEMA}.{tabla} "
                   f"FOR EACH ROW EXECUTE FUNCTION {ESQUEMA}.{funcion}()")


def upgrade() -> None:
    op.execute(f"ALTER TYPE {ESQUEMA}.tipo_evento_cronograma ADD VALUE IF NOT EXISTS 'anulado'")
    op.add_column("cronograma", sa.Column("anulado_at", sa.DateTime(timezone=True)), schema=ESQUEMA)
    op.add_column("cronograma", sa.Column("anulado_por", sa.BigInteger()), schema=ESQUEMA)
    op.add_column("cronograma", sa.Column("anulado_motivo", sa.Text()), schema=ESQUEMA)
    op.create_foreign_key("fk_cronograma_anulado_por_usuario", "cronograma", "usuario", ["anulado_por"],
                          ["id"], source_schema=ESQUEMA, referent_schema=ESQUEMA)
    op.create_index("ix_cronograma_anulado_por", "cronograma", ["anulado_por"], schema=ESQUEMA)
    op.drop_constraint("uq_cronograma_modulo_id_fecha", "cronograma", schema=ESQUEMA, type_="unique")
    op.create_index("uq_cronograma_modulo_id_fecha_activo", "cronograma", ["modulo_id", "fecha"],
                    unique=True, schema=ESQUEMA, postgresql_where=sa.text("anulado_at IS NULL"))
    _claves(cascada=True)
    op.execute("""
        CREATE FUNCTION riego.cronograma_validar_borrado() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF OLD.version_publicada_id IS NOT NULL OR OLD.num_publicaciones <> 0
               OR OLD.anulado_at IS NOT NULL
               OR EXISTS (SELECT 1 FROM riego.cronograma_version
                          WHERE cronograma_id = OLD.id AND publicada_at IS NOT NULL) THEN
                RAISE EXCEPTION 'El cronograma conserva historial: debe anularse'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN OLD;
        END;
        $$
    """)
    preparar_funcion("cronograma_validar_borrado()")
    op.execute("CREATE TRIGGER tg_cronograma_validar_borrado BEFORE DELETE ON riego.cronograma "
               "FOR EACH ROW EXECUTE FUNCTION riego.cronograma_validar_borrado()")
    op.execute("""
        CREATE FUNCTION riego.cronograma_dependencia_inmutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        DECLARE padre_existe boolean;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF TG_TABLE_NAME IN ('cronograma_version', 'cronograma_evento') THEN
                    SELECT EXISTS (SELECT 1 FROM riego.cronograma WHERE id = OLD.cronograma_id)
                        INTO padre_existe;
                ELSE
                    SELECT EXISTS (SELECT 1 FROM riego.cronograma_version WHERE id = OLD.version_id)
                        INTO padre_existe;
                END IF;
                -- El padre ya no existe solo durante la cascada del DELETE autorizado.
                IF NOT padre_existe AND pg_trigger_depth() > 1 THEN
                    RETURN OLD;
                END IF;
                IF TG_TABLE_NAME = 'cronograma_version' THEN
                    RAISE EXCEPTION 'Las versiones de cronograma no se pueden borrar individualmente'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
            ELSIF TG_TABLE_NAME = 'cronograma_version' THEN
                IF OLD.publicada_at IS NOT NULL THEN
                    RAISE EXCEPTION 'La versión % ya fue publicada y es inmutable', OLD.id
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                IF NEW.publicada_at IS NULL THEN
                    RAISE EXCEPTION 'Solo se puede fijar publicada_at y publicada_por'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                IF (to_jsonb(NEW) - 'publicada_at' - 'publicada_por')
                   IS DISTINCT FROM (to_jsonb(OLD) - 'publicada_at' - 'publicada_por') THEN
                    RAISE EXCEPTION 'La versión de cronograma es inmutable (solo se fija la publicación)'
                        USING ERRCODE = 'insufficient_privilege';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'La dependencia del cronograma es inmutable; solo se elimina con su borrador'
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$
    """)
    preparar_funcion("cronograma_dependencia_inmutable()")
    _triggers(cascada=True)


def downgrade() -> None:
    # Fallar antes de modificar nada si la unicidad antigua ya no puede restaurarse.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM riego.cronograma GROUP BY modulo_id, fecha HAVING count(*) > 1) THEN
                RAISE EXCEPTION 'No se puede bajar 0005: hay cronogramas con módulo y fecha repetidos';
            END IF;
        END $$
    """)
    _triggers(cascada=False)
    op.execute("DROP TRIGGER tg_cronograma_validar_borrado ON riego.cronograma")
    op.execute("DROP FUNCTION riego.cronograma_dependencia_inmutable()")
    op.execute("DROP FUNCTION riego.cronograma_validar_borrado()")
    _claves(cascada=False)
    op.drop_index("uq_cronograma_modulo_id_fecha_activo", table_name="cronograma", schema=ESQUEMA)
    op.create_unique_constraint("uq_cronograma_modulo_id_fecha", "cronograma", ["modulo_id", "fecha"], schema=ESQUEMA)
    op.drop_index("ix_cronograma_anulado_por", table_name="cronograma", schema=ESQUEMA)
    op.drop_constraint("fk_cronograma_anulado_por_usuario", "cronograma", schema=ESQUEMA, type_="foreignkey")
    for columna in ("anulado_motivo", "anulado_por", "anulado_at"):
        op.drop_column("cronograma", columna, schema=ESQUEMA)
