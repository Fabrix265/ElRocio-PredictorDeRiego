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


# --- configurar-rol-app con un dueño no superusuario (como en Supabase) -------

def _como_dueno_de_supabase(conexion: Connection) -> None:
    """Simula el rol ``postgres`` de Supabase: CREATEROLE/CREATEDB/BYPASSRLS, sin SUPERUSER.
    Los roles se crean dentro de la transacción del test y se deshacen al final."""
    conexion.exec_driver_sql(
        "CREATE ROLE zz_supa_owner NOLOGIN NOSUPERUSER CREATEROLE CREATEDB BYPASSRLS"
    )
    conexion.exec_driver_sql("SET LOCAL ROLE zz_supa_owner")
    # Igual que la migración 0001 (quien crea el rol queda con ADMIN sobre él).
    conexion.exec_driver_sql(
        "CREATE ROLE zz_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
    )


def test_configurar_rol_funciona_sin_superusuario(conexion: Connection):
    from app.cli import atributos_de_mas, configurar_rol

    _como_dueno_de_supabase(conexion)
    # La sentencia anterior (con NOSUPERUSER) falla para un dueño no superusuario.
    error = _ejecutar_falla(
        conexion,
        "ALTER ROLE zz_app WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD 'x'",
    )
    assert _es_privilegio_insuficiente(error)

    assert atributos_de_mas(conexion, "zz_app") == []
    configurar_rol(conexion, "zz_app", "clave-del-rol-app-2026")
    fila = conexion.execute(
        text("SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
             "FROM pg_roles WHERE rolname = 'zz_app'")
    ).one()
    assert tuple(fila) == (True, False, False, False, False)
    conexion.exec_driver_sql("RESET ROLE")  # pg_authid solo lo lee un superusuario
    verificador = conexion.execute(
        text("SELECT rolpassword FROM pg_authid WHERE rolname = 'zz_app'")
    ).scalar_one()
    assert verificador.startswith("SCRAM-SHA-256$") and "clave-del-rol" not in verificador


def test_atributos_de_mas_detecta_roles_peligrosos(conexion: Connection):
    from app.cli import atributos_de_mas

    _como_dueno_de_supabase(conexion)
    assert atributos_de_mas(conexion, "zz_supa_owner") == ["BYPASSRLS", "CREATEROLE", "CREATEDB"]
    assert atributos_de_mas(conexion, "no_existe_este_rol") is None


def test_cli_configurar_rol_app_no_da_login_a_un_rol_con_atributos_de_mas(
    engine, monkeypatch, capsys
):
    from app import cli

    llamadas = []
    monkeypatch.setenv("RIEGO_APP_PASSWORD", "clave-larga-del-rol-2026")
    monkeypatch.setattr(cli, "configurar_rol", lambda *_a: llamadas.append(True))
    monkeypatch.setattr(cli, "atributos_de_mas", lambda *_a: ["BYPASSRLS"])
    assert cli_main(["configurar-rol-app"]) == 1
    assert "BYPASSRLS" in capsys.readouterr().err and not llamadas

    monkeypatch.setattr(cli, "atributos_de_mas", lambda *_a: [])
    assert cli_main(["configurar-rol-app"]) == 0
    assert llamadas == [True]


# --- riego_registro: versiones inmutables (migración 0003) --------------------

def _insertar_registro(conexion: Connection, *, fecha: str = "2026-11-01", version: int = 1,
                       vigente: bool = True) -> int:
    turno = conexion.execute(
        text(f"SELECT t.id, t.modulo_id FROM {ESQUEMA}.turno t WHERE t.codigo = 'TE01'")
    ).one()
    return conexion.execute(
        text(
            f"INSERT INTO {ESQUEMA}.riego_registro (modulo_id, turno_id, fecha, version, vigente, "
            "estado, origen, sin_riego, contenido_sha256) "
            "VALUES (:m, :t, :f, :v, :vig, 'aplicado', 'manual', true, repeat('a', 64)) RETURNING id"
        ),
        {"m": turno.modulo_id, "t": turno.id, "f": fecha, "v": version, "vig": vigente},
    ).scalar_one()


def test_riego_app_no_reescribe_ni_borra_versiones_de_riego(conexion: Connection):
    conexion.exec_driver_sql("SET LOCAL ROLE riego_app")
    id_ = _insertar_registro(conexion)
    p = {"id": id_}
    for sql in (
        f"UPDATE {ESQUEMA}.riego_registro SET estado = 'provisional', "
        "contenido_sha256 = repeat('f', 64), sin_riego = false WHERE id = :id",
        f"UPDATE {ESQUEMA}.riego_registro SET origen = 'excel' WHERE id = :id",
        f"DELETE FROM {ESQUEMA}.riego_registro WHERE id = :id",
    ):
        assert _es_privilegio_insuficiente(_ejecutar_falla(conexion, sql, p)), sql

    # Editar = nueva versión: la anterior deja de ser vigente (único cambio permitido).
    conexion.execute(text(f"UPDATE {ESQUEMA}.riego_registro SET vigente = false WHERE id = :id"), p)
    _insertar_registro(conexion, version=2)
    error = _ejecutar_falla(
        conexion, f"UPDATE {ESQUEMA}.riego_registro SET vigente = true WHERE id = :id", p
    )
    assert "Solo se puede marcar" in str(error.orig)
    filas = conexion.execute(
        text(f"SELECT version, vigente FROM {ESQUEMA}.riego_registro ORDER BY version")
    ).all()
    assert [tuple(f) for f in filas] == [(1, False), (2, True)]


def test_trigger_riego_registro_tambien_para_el_dueno(conexion: Connection):
    id_ = _insertar_registro(conexion)
    p = {"id": id_}
    error = _ejecutar_falla(
        conexion, f"UPDATE {ESQUEMA}.riego_registro SET vigente = false, motivo = 'x' WHERE id = :id", p
    )
    assert "inmutable" in str(error.orig)
    error = _ejecutar_falla(conexion, f"DELETE FROM {ESQUEMA}.riego_registro WHERE id = :id", p)
    assert "no se borran" in str(error.orig)


def test_verificar_detecta_update_de_mas_en_riego_registro(conexion: Connection):
    conexion.exec_driver_sql(f"GRANT UPDATE (estado) ON {ESQUEMA}.riego_registro TO riego_app")
    assert any("riego_registro" in p and "estado" in p for p in verificar_seguridad(conexion))


# --- updated_at por trigger ---------------------------------------------------

def test_updated_at_se_actualiza_en_upsert(conexion: Connection):
    from sqlalchemy.dialects.postgresql import insert

    from app.models import AmbienteDiario

    conexion.exec_driver_sql("SET LOCAL ROLE riego_app")
    fundo_id = conexion.execute(
        text(f"SELECT id FROM {ESQUEMA}.fundo WHERE codigo = 'EN01'")
    ).scalar_one()
    tabla = AmbienteDiario.__table__
    conexion.execute(
        tabla.insert().values(fundo_id=fundo_id, fecha="2026-11-01", t_media=20.0,
                              created_at="2020-06-01T12:00:00Z", updated_at="2020-06-01T12:00:00Z")
    )
    upsert = insert(tabla).values(fundo_id=fundo_id, fecha="2026-11-01", t_media=21.5)
    # on_conflict_do_update no aplica el onupdate del ORM: lo cubre el trigger de la BD.
    conexion.execute(upsert.on_conflict_do_update(
        index_elements=["fundo_id", "fecha"], set_={"t_media": upsert.excluded.t_media}
    ))
    fila = conexion.execute(
        text(f"SELECT t_media, created_at, updated_at, now() AS ahora FROM {ESQUEMA}.ambiente_diario")
    ).one()
    assert fila.t_media == 21.5
    assert fila.created_at.year == 2020
    assert fila.updated_at == fila.ahora


# --- Ayudas para migraciones nuevas -------------------------------------------

def test_preparar_tabla_y_funcion_dejan_la_seguridad_de_0001(conexion: Connection):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from app.db.migraciones import preparar_funcion, preparar_tabla

    conexion.exec_driver_sql(
        f"CREATE TABLE {ESQUEMA}.zz_prueba (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY, "
        "nombre text)"
    )
    conexion.exec_driver_sql(
        f"CREATE FUNCTION {ESQUEMA}.zz_funcion() RETURNS int LANGUAGE sql AS 'SELECT 1'"
    )
    # Sin preparar: verificar_seguridad lo detecta.
    problemas = verificar_seguridad(conexion)
    assert any("zz_prueba no tiene RLS" in p for p in problemas)
    assert any("zz_funcion" in p for p in problemas)

    contexto = MigrationContext.configure(conexion)
    with Operations.context(contexto):
        preparar_tabla("zz_prueba", modo="insercion")
        preparar_funcion("zz_funcion()")
    assert verificar_seguridad(conexion) == []

    conexion.exec_driver_sql("SET LOCAL ROLE riego_app")
    conexion.execute(text(f"INSERT INTO {ESQUEMA}.zz_prueba (nombre) VALUES ('ok')"))
    assert conexion.execute(text(f"SELECT count(*) FROM {ESQUEMA}.zz_prueba")).scalar() == 1
    error = _ejecutar_falla(conexion, f"DELETE FROM {ESQUEMA}.zz_prueba")
    assert _es_privilegio_insuficiente(error)
