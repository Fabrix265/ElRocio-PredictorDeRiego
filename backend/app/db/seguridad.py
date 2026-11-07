"""Verificación de la seguridad del esquema ``riego`` en la base de datos.

- :func:`verificar_seguridad`: la usan ``python -m app.cli verificar-seguridad-bd`` y los tests.
- :func:`problemas_rol_conexion`: la usan el arranque de la API y ``/health`` para comprobar que
  la aplicación se conecta como ``riego_app`` (no como el dueño, que se salta RLS).

Devuelven la lista de problemas encontrados (vacía = todo en orden). Solo leen catálogos.
"""

from __future__ import annotations

from sqlalchemy import Connection, text

from app.db.base import ESQUEMA

ROL_APP = "riego_app"
ROLES_PROHIBIDOS = ("anon", "authenticated")

# Tablas de solo inserción para riego_app (y protegidas por trigger).
SOLO_INSERCION = (
    "auditoria", "cronograma_evento", "prediccion_entrada",
    "riego_ciclo", "cronograma_ciclo", "cronograma_turno",
)
SIN_TRUNCATE = ("auditoria", "cronograma_evento")
# Tablas con UPDATE solo en algunas columnas (y trigger tg_<tabla>_inmutable), sin DELETE.
COLUMNAS_ACTUALIZABLES = {
    "cronograma_version": {"publicada_at", "publicada_por"},
    "riego_registro": {"vigente"},  # migración 0003
}
COLUMNAS_PUBLICACION = COLUMNAS_ACTUALIZABLES["cronograma_version"]
# updated_at mantenido por trigger (tg_<tabla>_updated_at, migración 0003).
TABLAS_UPDATED_AT = (
    "usuario", "cronograma", "meteo_lectura", "phytech_suelo_horario", "phytech_planta_diario",
    "ambiente_diario",
)
TABLAS_SIN_INSERT = ("alembic_version",)
PRIVILEGIOS_TABLA = "SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER"


def problemas_rol_conexion(conexion) -> list[str]:
    """Problemas del rol con que está conectada la app (``conexion``: Connection o Session).

    Debe ser ``riego_app``: sin SUPERUSER ni BYPASSRLS y sin poder actuar como el dueño del
    esquema (el dueño no está sujeto a RLS ni a los permisos de solo inserción).
    """
    fila = conexion.execute(
        text(
            """
            SELECT current_user AS usuario, r.rolsuper, r.rolbypassrls,
                   COALESCE((SELECT pg_has_role(current_user, n.nspowner, 'USAGE')
                             FROM pg_namespace n WHERE n.nspname = :esquema), false) AS dueno
            FROM pg_roles r WHERE r.rolname = current_user
            """
        ),
        {"esquema": ESQUEMA},
    ).one()
    problemas = []
    if fila.usuario != ROL_APP:
        problemas.append(f"la conexión usa el rol {fila.usuario}, no {ROL_APP}")
    if fila.rolsuper:
        problemas.append(f"el rol {fila.usuario} es superusuario")
    if fila.rolbypassrls:
        problemas.append(f"el rol {fila.usuario} tiene BYPASSRLS (se salta RLS)")
    if fila.dueno:
        problemas.append(f"el rol {fila.usuario} es (o actúa como) el dueño del esquema {ESQUEMA}")
    return problemas


def _filas(conexion: Connection, sql: str, **params) -> list:
    return list(conexion.execute(text(sql), params))


def _existe_rol(conexion: Connection, rol: str) -> bool:
    return bool(conexion.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": rol}).first())


def verificar_seguridad(conexion: Connection) -> list[str]:
    problemas: list[str] = []
    p = {"esquema": ESQUEMA}

    if not _filas(conexion, "SELECT 1 FROM pg_namespace WHERE nspname = :esquema", **p):
        return [f"No existe el esquema {ESQUEMA} (¿faltan las migraciones?)"]

    tablas = _filas(
        conexion,
        """
        SELECT c.oid, c.relname, c.relrowsecurity, pg_get_userbyid(c.relowner) AS dueno
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = :esquema AND c.relkind IN ('r', 'p')
        ORDER BY c.relname
        """,
        **p,
    )
    if not tablas:
        problemas.append(f"El esquema {ESQUEMA} no tiene tablas")

    # 1) RLS en todas las tablas con una única política, para riego_app.
    for tabla in tablas:
        if not tabla.relrowsecurity:
            problemas.append(f"La tabla {tabla.relname} no tiene RLS habilitado")
        politicas = _filas(
            conexion,
            """
            SELECT polname, polpermissive,
                   ARRAY(SELECT CASE WHEN r = 0 THEN 'public' ELSE pg_get_userbyid(r) END
                         FROM unnest(polroles) AS r) AS roles
            FROM pg_policy WHERE polrelid = :oid
            """,
            oid=tabla.oid,
        )
        if not any(list(pol.roles) == [ROL_APP] for pol in politicas):
            problemas.append(f"La tabla {tabla.relname} no tiene la política para {ROL_APP}")
        for pol in politicas:
            otros = [r for r in pol.roles if r != ROL_APP]
            if otros:
                problemas.append(
                    f"La política {pol.polname} de {tabla.relname} aplica a otros roles: {otros}"
                )

    # 2) Nada para PUBLIC (grantee 0) en esquema, tablas, secuencias ni funciones.
    publicos = _filas(
        conexion,
        """
        SELECT 'esquema' AS tipo, n.nspname AS nombre
        FROM pg_namespace n, aclexplode(n.nspacl) a
        WHERE n.nspname = :esquema AND a.grantee = 0
        UNION ALL
        SELECT CASE c.relkind WHEN 'S' THEN 'secuencia' ELSE 'tabla' END, c.relname
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, aclexplode(c.relacl) a
        WHERE n.nspname = :esquema AND a.grantee = 0
        UNION ALL
        SELECT 'función', p.proname
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = :esquema
          AND (p.proacl IS NULL OR EXISTS (SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee = 0))
        """,
        **p,
    )
    for fila in publicos:
        problemas.append(f"PUBLIC tiene privilegios sobre {fila.tipo} {fila.nombre}")

    # 3) anon / authenticated (Supabase) sin ningún privilegio, si existen.
    for rol in ROLES_PROHIBIDOS:
        if not _existe_rol(conexion, rol):
            continue
        if _filas(conexion, "SELECT 1 WHERE has_schema_privilege(:r, :esquema, 'USAGE,CREATE')",
                  r=rol, **p):
            problemas.append(f"El rol {rol} tiene privilegios sobre el esquema {ESQUEMA}")
        for tabla in tablas:
            if _filas(conexion, "SELECT 1 WHERE has_table_privilege(:r, :oid, :privs)",
                      r=rol, oid=tabla.oid, privs=PRIVILEGIOS_TABLA):
                problemas.append(f"El rol {rol} tiene privilegios sobre la tabla {tabla.relname}")
        secuencias = _filas(
            conexion,
            """
            SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :esquema
              AND CASE WHEN c.relkind = 'S'
                       THEN has_sequence_privilege(:r, c.oid, 'USAGE,SELECT,UPDATE')
                       ELSE false END
            """,
            r=rol, **p,
        )
        for sec in secuencias:
            problemas.append(f"El rol {rol} tiene privilegios sobre la secuencia {sec.relname}")

    # 4) riego_app: existe, sin superpoderes, no es dueño de nada ni miembro del dueño.
    rol_app = conexion.execute(
        text("SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = :r"),
        {"r": ROL_APP},
    ).first()
    if rol_app is None:
        problemas.append(f"No existe el rol {ROL_APP}")
        return problemas
    if rol_app.rolsuper or rol_app.rolbypassrls or rol_app.rolcreaterole or rol_app.rolcreatedb:
        problemas.append(f"El rol {ROL_APP} tiene atributos de más (SUPERUSER/BYPASSRLS/CREATEROLE/CREATEDB)")
    for tabla in tablas:
        if tabla.dueno == ROL_APP:
            problemas.append(f"{ROL_APP} es dueño de la tabla {tabla.relname}")
    duenos = {t.dueno for t in tablas}
    for dueno in duenos:
        if _filas(conexion, "SELECT 1 WHERE pg_has_role(:r, :d, 'MEMBER')", r=ROL_APP, d=dueno):
            problemas.append(f"{ROL_APP} es miembro del rol dueño {dueno}")

    # 5) Tablas de solo inserción: sin UPDATE/DELETE/TRUNCATE para riego_app; triggers presentes.
    nombres = {t.relname: t for t in tablas}
    for nombre in SOLO_INSERCION:
        tabla = nombres.get(nombre)
        if tabla is None:
            problemas.append(f"Falta la tabla {nombre}")
            continue
        for privilegio in ("UPDATE", "DELETE", "TRUNCATE"):
            if _filas(conexion, "SELECT 1 WHERE has_table_privilege(:r, :oid, :p)",
                      r=ROL_APP, oid=tabla.oid, p=privilegio):
                problemas.append(f"{ROL_APP} tiene {privilegio} sobre {nombre}")
    for nombre, permitidas in COLUMNAS_ACTUALIZABLES.items():
        tabla = nombres.get(nombre)
        if tabla is None:
            continue
        for privilegio in ("DELETE", "TRUNCATE"):
            if _filas(conexion, "SELECT 1 WHERE has_table_privilege(:r, :oid, :p)",
                      r=ROL_APP, oid=tabla.oid, p=privilegio):
                problemas.append(f"{ROL_APP} tiene {privilegio} sobre {nombre}")
        columnas = _filas(
            conexion,
            """
            SELECT attname FROM pg_attribute
            WHERE attrelid = :oid AND attnum > 0 AND NOT attisdropped
              AND has_column_privilege(:r, :oid, attnum, 'UPDATE')
            """,
            oid=tabla.oid, r=ROL_APP,
        )
        extra = {c.attname for c in columnas} - permitidas
        if extra:
            problemas.append(f"{ROL_APP} puede actualizar columnas de {nombre}: {sorted(extra)}")

    # 6) riego_app necesita leer todas las tablas e insertar en las de la app (si falta, la app
    #    falla en ejecución con "permission denied").
    for tabla in tablas:
        privilegios = ("SELECT",) if tabla.relname in TABLAS_SIN_INSERT else ("SELECT", "INSERT")
        for privilegio in privilegios:
            if not _filas(conexion, "SELECT 1 WHERE has_table_privilege(:r, :oid, :p)",
                          r=ROL_APP, oid=tabla.oid, p=privilegio):
                problemas.append(f"{ROL_APP} no tiene {privilegio} sobre {tabla.relname}")

    # 7) Funciones del esquema: anon/authenticated no las pueden ejecutar.
    for rol in ROLES_PROHIBIDOS:
        if not _existe_rol(conexion, rol):
            continue
        for fila in _filas(
            conexion,
            """
            SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = :esquema AND has_function_privilege(:r, p.oid, 'EXECUTE')
            """,
            r=rol, **p,
        ):
            problemas.append(f"El rol {rol} puede ejecutar la función {fila.proname}")

    triggers = {
        (fila.tabla, fila.tgname)
        for fila in _filas(
            conexion,
            """
            SELECT c.relname AS tabla, t.tgname
            FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :esquema AND NOT t.tgisinternal AND t.tgenabled <> 'D'
            """,
            **p,
        )
    }
    esperados = [(t, f"tg_{t}_inmutable") for t in (*SOLO_INSERCION, *COLUMNAS_ACTUALIZABLES)]
    esperados += [(t, f"tg_{t}_sin_truncate") for t in SIN_TRUNCATE]
    esperados += [(t, f"tg_{t}_updated_at") for t in TABLAS_UPDATED_AT]
    for tabla, trigger in esperados:
        if tabla in nombres and (tabla, trigger) not in triggers:
            problemas.append(f"Falta o está deshabilitado el trigger {trigger} en {tabla}")

    return problemas
