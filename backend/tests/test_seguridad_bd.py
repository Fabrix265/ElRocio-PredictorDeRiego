"""RLS, privilegios de riego_app/anon/authenticated y triggers de inmutabilidad."""

from __future__ import annotations

import pytest
from psycopg import errors as pg_errors
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from app.cli import main as cli_main
from app.db.base import ESQUEMA
from app.db.seguridad import SOLO_INSERCION, verificar_seguridad

PRIVILEGIOS = "SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"


def _ejecutar_falla(conexion: Connection, sql: str, params: dict | None = None) -> DBAPIError:
    """Ejecuta ``sql`` dentro de un SAVEPOINT y devuelve el error (el test sigue usable)."""
    punto = conexion.begin_nested()
    with pytest.raises(DBAPIError) as info:
        conexion.execute(text(sql), params or {})
    punto.rollback()
    return info.value


def _es_privilegio_insuficiente(error: DBAPIError) -> bool:
    return isinstance(error.orig, pg_errors.InsufficientPrivilege)


def _insertar_auditoria(conexion: Connection) -> int:
    return conexion.execute(
        text(
            f"INSERT INTO {ESQUEMA}.auditoria (accion, entidad, entidad_id, detalle) "
            "VALUES ('prueba', 'test', '1', '{}'::jsonb) RETURNING id"
        )
    ).scalar_one()


def test_verificar_seguridad_sin_problemas(conexion: Connection):
    assert verificar_seguridad(conexion) == []


def test_cli_verificar_seguridad_bd(engine, capsys):
    assert cli_main(["verificar-seguridad-bd"]) == 0
    assert "OK" in capsys.readouterr().out


def test_todas_las_tablas_con_rls_y_politica_solo_para_riego_app(conexion: Connection):
    filas = conexion.execute(
        text(
            """
            SELECT c.relname, c.relrowsecurity,
                   (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS politicas,
                   (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid
                      AND p.polroles = ARRAY[(SELECT oid FROM pg_roles WHERE rolname = 'riego_app')]::oid[])
                      AS politicas_app
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :e AND c.relkind IN ('r', 'p')
            """
        ),
        {"e": ESQUEMA},
    ).all()
    assert len(filas) == 33  # 32 tablas + alembic_version
    for fila in filas:
        assert fila.relrowsecurity, fila.relname
        assert (fila.politicas, fila.politicas_app) == (1, 1), fila.relname


@pytest.mark.parametrize("rol", ["anon", "authenticated", "public"])
def test_roles_publicos_sin_privilegios(conexion: Connection, rol: str):
    existe = rol == "public" or conexion.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": rol}
    ).first()
    if not existe:
        pytest.skip(f"El rol {rol} no existe en este servidor")
    if rol == "public":
        # PUBLIC no es un rol consultable con has_*_privilege: se revisan las ACL (grantee 0).
        con_acl = conexion.execute(
            text(
                """
                SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,
                     aclexplode(c.relacl) a
                WHERE n.nspname = :e AND a.grantee = 0
                """
            ),
            {"e": ESQUEMA},
        ).all()
        assert con_acl == []
        return
    assert not conexion.execute(
        text("SELECT has_schema_privilege(:r, :e, 'USAGE,CREATE')"), {"r": rol, "e": ESQUEMA}
    ).scalar()
    con_privilegios = conexion.execute(
        text(
            """
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :e AND c.relkind IN ('r', 'p', 'S')
              AND CASE WHEN c.relkind = 'S'
                       THEN has_sequence_privilege(:r, c.oid, 'USAGE,SELECT,UPDATE')
                       ELSE has_table_privilege(:r, c.oid, :p) END
            """
        ),
        {"e": ESQUEMA, "r": rol, "p": PRIVILEGIOS},
    ).all()
    assert con_privilegios == []


def test_verificar_detecta_privilegios_indebidos(conexion: Connection):
    conexion.exec_driver_sql(f"GRANT SELECT ON {ESQUEMA}.turno TO PUBLIC")
    conexion.exec_driver_sql(f"ALTER TABLE {ESQUEMA}.lote DISABLE ROW LEVEL SECURITY")
    problemas = verificar_seguridad(conexion)
    assert any("PUBLIC" in p and "turno" in p for p in problemas)
    assert any("lote" in p and "RLS" in p for p in problemas)


def test_rol_sin_politica_no_ve_filas(conexion: Connection):
    # Un rol con GRANT pero sin política RLS no ve nada: la política es solo para riego_app.
    conexion.exec_driver_sql("CREATE ROLE riego_prueba_sin_politica NOLOGIN")
    conexion.exec_driver_sql(f"GRANT USAGE ON SCHEMA {ESQUEMA} TO riego_prueba_sin_politica")
    conexion.exec_driver_sql(f"GRANT SELECT ON {ESQUEMA}.turno TO riego_prueba_sin_politica")
    conexion.exec_driver_sql("SET LOCAL ROLE riego_prueba_sin_politica")
    assert conexion.execute(text(f"SELECT count(*) FROM {ESQUEMA}.turno")).scalar() == 0
    conexion.exec_driver_sql("SET LOCAL ROLE riego_app")
    assert conexion.execute(text(f"SELECT count(*) FROM {ESQUEMA}.turno")).scalar() == 5


def test_riego_app_inserta_y_lee_auditoria_pero_no_modifica(conexion: Connection):
    conexion.exec_driver_sql("SET LOCAL ROLE riego_app")
    id_ = _insertar_auditoria(conexion)
    assert conexion.execute(
        text(f"SELECT accion FROM {ESQUEMA}.auditoria WHERE id = :id"), {"id": id_}
    ).scalar() == "prueba"
    for sql in (
        f"UPDATE {ESQUEMA}.auditoria SET accion = 'otra' WHERE id = :id",
        f"DELETE FROM {ESQUEMA}.auditoria WHERE id = :id",
        f"TRUNCATE {ESQUEMA}.auditoria",
    ):
        error = _ejecutar_falla(conexion, sql, {"id": id_})
        assert _es_privilegio_insuficiente(error), sql


@pytest.mark.parametrize("tabla", SOLO_INSERCION)
def test_riego_app_sin_update_delete_en_tablas_de_solo_insercion(conexion: Connection, tabla: str):
    conexion.exec_driver_sql("SET LOCAL ROLE riego_app")
    for sql in (f"UPDATE {ESQUEMA}.{tabla} SET id = id", f"DELETE FROM {ESQUEMA}.{tabla}"):
        assert _es_privilegio_insuficiente(_ejecutar_falla(conexion, sql)), sql


def test_triggers_bloquean_al_dueno_en_auditoria(conexion: Connection):
    # Aunque el rol tenga privilegios (dueño), los triggers rechazan modificar la auditoría.
    id_ = _insertar_auditoria(conexion)
    for sql in (
        f"UPDATE {ESQUEMA}.auditoria SET accion = 'otra' WHERE id = :id",
        f"DELETE FROM {ESQUEMA}.auditoria WHERE id = :id",
        f"TRUNCATE {ESQUEMA}.auditoria",
        f"TRUNCATE {ESQUEMA}.cronograma_evento",
    ):
        error = _ejecutar_falla(conexion, sql, {"id": id_})
        assert "solo inserción" in str(error.orig), sql


def _crear_version(conexion: Connection) -> int:
    modulo_id = conexion.execute(
        text(f"SELECT id FROM {ESQUEMA}.modulo WHERE codigo = 'EN01-MOD5'")
    ).scalar_one()
    cronograma_id = conexion.execute(
        text(
            f"INSERT INTO {ESQUEMA}.cronograma (modulo_id, fecha) VALUES (:m, DATE '2026-11-08') "
            "RETURNING id"
        ),
        {"m": modulo_id},
    ).scalar_one()
    return conexion.execute(
        text(
            f"INSERT INTO {ESQUEMA}.cronograma_version (cronograma_id, numero, origen) "
            "VALUES (:c, 1, 'modelo') RETURNING id"
        ),
        {"c": cronograma_id},
    ).scalar_one()


def test_cronograma_version_solo_se_publica_una_vez(conexion: Connection):
    conexion.exec_driver_sql("SET LOCAL ROLE riego_app")
    version_id = _crear_version(conexion)
    p = {"id": version_id}

    # riego_app no tiene UPDATE sobre otras columnas ni DELETE.
    error = _ejecutar_falla(
        conexion, f"UPDATE {ESQUEMA}.cronograma_version SET preliminar = true WHERE id = :id", p
    )
    assert _es_privilegio_insuficiente(error)
    error = _ejecutar_falla(conexion, f"DELETE FROM {ESQUEMA}.cronograma_version WHERE id = :id", p)
    assert _es_privilegio_insuficiente(error)

    # Fijar la publicación una vez funciona; la segunda vez lo rechaza el trigger.
    conexion.execute(
        text(f"UPDATE {ESQUEMA}.cronograma_version SET publicada_at = now() WHERE id = :id"), p
    )
    error = _ejecutar_falla(
        conexion, f"UPDATE {ESQUEMA}.cronograma_version SET publicada_at = now() WHERE id = :id", p
    )
    assert "ya fue publicada" in str(error.orig)


def test_trigger_cronograma_version_para_el_dueno(conexion: Connection):
    version_id = _crear_version(conexion)
    p = {"id": version_id}
    error = _ejecutar_falla(
        conexion, f"UPDATE {ESQUEMA}.cronograma_version SET preliminar = true WHERE id = :id", p
    )
    assert "Solo se puede fijar" in str(error.orig)
    error = _ejecutar_falla(
        conexion,
        f"UPDATE {ESQUEMA}.cronograma_version SET publicada_at = now(), numero = 9 WHERE id = :id",
        p,
    )
    assert "inmutable" in str(error.orig)
    error = _ejecutar_falla(conexion, f"DELETE FROM {ESQUEMA}.cronograma_version WHERE id = :id", p)
    assert "no se pueden borrar" in str(error.orig)


def test_riego_app_atributos_minimos(conexion: Connection):
    fila = conexion.execute(
        text(
            "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
            "FROM pg_roles WHERE rolname = 'riego_app'"
        )
    ).one()
    assert tuple(fila) == (False, False, False, False)
