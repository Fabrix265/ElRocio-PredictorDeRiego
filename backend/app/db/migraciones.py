"""Ayudas para las migraciones de Alembic (F2–F5): cada tabla o función nueva del esquema
``riego`` debe quedar con la misma seguridad que dejó la migración 0001.

Postgres no aplica ``ALTER DEFAULT PRIVILEGES IN SCHEMA ... REVOKE`` sobre los privilegios por
defecto globales (el EXECUTE de PUBLIC sobre funciones viene de fábrica), y ``riego_app`` no tiene
privilegios por defecto: sin estas ayudas una tabla nueva quedaría sin RLS ni GRANT, y una función
nueva, ejecutable por PUBLIC, ``anon`` y ``authenticated``.

Uso dentro de ``upgrade()``::

    op.create_table("mi_tabla", ..., schema="riego")
    preparar_tabla("mi_tabla", modo="crud")          # o "insercion" (solo SELECT/INSERT)
    op.execute("CREATE FUNCTION riego.mi_funcion() ...")
    preparar_funcion("mi_funcion()")

``python -m app.cli verificar-seguridad-bd`` detecta lo que falte.
"""

from __future__ import annotations

from typing import Literal

from alembic import op

ESQUEMA = "riego"
ROL_APP = "riego_app"
ROLES_SUPABASE = ("anon", "authenticated")

PRIVILEGIOS_POR_MODO = {
    "crud": "SELECT, INSERT, UPDATE, DELETE",
    "insercion": "SELECT, INSERT",
}


def _revocar_de_roles_supabase(objeto: str) -> None:
    """``REVOKE ALL ON <objeto>`` para ``anon`` y ``authenticated``, solo si existen."""
    roles = ", ".join(f"'{r}'" for r in ROLES_SUPABASE)
    objeto_sql = objeto.replace("'", "''")
    op.execute(
        f"""
        DO $$
        DECLARE
            rol text;
        BEGIN
            FOREACH rol IN ARRAY ARRAY[{roles}] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = rol) THEN
                    EXECUTE format('REVOKE ALL ON {objeto_sql} FROM %I', rol);
                END IF;
            END LOOP;
        END
        $$
        """
    )


def preparar_funcion(firma: str) -> None:
    """Quita el EXECUTE de PUBLIC, ``anon`` y ``authenticated`` sobre ``riego.<firma>``.

    ``firma`` incluye los tipos de los argumentos, p. ej. ``"mi_funcion(integer)"`` o
    ``"fijar_updated_at()"``.
    """
    objeto = f"FUNCTION {ESQUEMA}.{firma}"
    op.execute(f"REVOKE ALL ON {objeto} FROM PUBLIC")
    _revocar_de_roles_supabase(objeto)


def preparar_tabla(tabla: str, *, modo: Literal["crud", "insercion"] = "crud") -> None:
    """GRANT para ``riego_app`` según el modo, RLS con la política única de ``riego_app``,
    USAGE/SELECT en las secuencias de la tabla y nada para PUBLIC/``anon``/``authenticated``.

    ``modo="insercion"``: la tabla es de solo inserción para la app (agregar además un trigger
    que rechace UPDATE/DELETE, como ``riego.rechazar_modificacion()``).
    """
    if modo not in PRIVILEGIOS_POR_MODO:
        raise ValueError(f"modo desconocido: {modo}")
    nombre = f"{ESQUEMA}.{tabla}"
    op.execute(f"REVOKE ALL ON {nombre} FROM PUBLIC")
    _revocar_de_roles_supabase(f"TABLE {nombre}")
    op.execute(f"GRANT {PRIVILEGIOS_POR_MODO[modo]} ON {nombre} TO {ROL_APP}")
    op.execute(f"ALTER TABLE {nombre} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {ROL_APP}_acceso ON {nombre} AS PERMISSIVE FOR ALL "
        f"TO {ROL_APP} USING (true) WITH CHECK (true)"
    )
    # Secuencias de las columnas identity/serial de la tabla.
    tabla_sql = nombre.replace("'", "''")
    op.execute(
        f"""
        DO $$
        DECLARE
            secuencia text;
        BEGIN
            FOR secuencia IN
                SELECT pg_get_serial_sequence('{tabla_sql}', a.attname)
                FROM pg_attribute a
                WHERE a.attrelid = '{tabla_sql}'::regclass AND a.attnum > 0 AND NOT a.attisdropped
                  AND pg_get_serial_sequence('{tabla_sql}', a.attname) IS NOT NULL
            LOOP
                EXECUTE format('REVOKE ALL ON SEQUENCE %s FROM PUBLIC', secuencia);
                EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %s TO {ROL_APP}', secuencia);
            END LOOP;
        END
        $$
        """
    )
