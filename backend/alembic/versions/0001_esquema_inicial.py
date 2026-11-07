"""Esquema inicial completo de ``riego``.

Escrita a partir del autogenerate y revisada a mano. Crea:

1. Los enums de estados.
2. Las 32 tablas de la sección 2.2 de docs/propuesta_mvp.md (incluidas las de F2–F5), con sus
   claves foráneas, índices y únicas (p. ej. el índice único parcial de ``riego_registro``).
3. Triggers de inmutabilidad: ``auditoria`` y ``cronograma_evento`` (sin UPDATE/DELETE/TRUNCATE),
   ``cronograma_version`` (solo fijar ``publicada_at/por`` una vez; sin DELETE) y ``riego_ciclo``,
   ``cronograma_ciclo``, ``cronograma_turno`` y ``prediccion_entrada`` (sin UPDATE/DELETE).
4. El rol ``riego_app`` (NOLOGIN; ``python -m app.cli configurar-rol-app`` le da LOGIN y
   contraseña) con privilegios mínimos; RLS en **todas** las tablas (también ``alembic_version``)
   con una sola política, para ``riego_app``; y REVOKE para PUBLIC, ``anon`` y ``authenticated``.

Todo con esquema explícito (no depende de ``search_path``).

Revision ID: 0001
Revises:
Create Date: 2026-11-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ESQUEMA = "riego"
ROL_APP = "riego_app"

# Valores de cada enum en esta versión del esquema (agregar valores = nueva migración).
ENUMS: dict[str, tuple[str, ...]] = {
    "rol_usuario": ("admin", "encargado", "programador", "subgerente"),
    "tipo_intento": ("login", "recuperar", "restablecer"),
    "estado_correo": ("pendiente", "enviando", "enviado", "error", "sin_destinatarios"),
    "disparo_ingesta": ("programado", "manual", "script"),
    "estado_ingesta": ("en_curso", "ok", "parcial", "error"),
    "origen_meteo": ("excel_historico", "weatherlink"),
    "estado_riego": ("provisional", "aplicado"),
    "origen_riego": ("historico", "cronograma", "excel", "manual", "controlador"),
    "estado_carga": ("previsualizada", "confirmada", "descartada", "vencida"),
    "resultado_carga": (
        "nuevo", "igual", "reemplaza_provisional", "reemplaza_aplicado", "sin_riego", "error",
    ),
    "tipo_generacion": ("generar", "regenerar"),
    "estado_cronograma": ("borrador", "publicado", "visto", "correccion_solicitada"),
    "origen_version": ("modelo", "regenerado", "correccion", "edicion"),
    "origen_riego_d1": ("aplicado", "provisional", "cronograma", "ninguno"),
    "tipo_evento_cronograma": (
        "generado", "regenerado", "corregido", "borrador_descartado", "publicado", "modificado",
        "visto_programador", "abierto_programador", "visto_subgerente", "correccion_solicitada",
        "correccion_atendida", "correccion_mantenida", "riego_provisional_creado",
        "riego_provisional_actualizado", "riego_reemplazado_excel", "riego_marcado_aplicado",
        "exportado",
    ),
}

# Tablas en orden de creación (el downgrade las borra al revés).
TABLAS = (
    "empresa", "intento_login", "modelo_version", "motivo_correccion", "usuario", "auditoria",
    "fundo", "ingesta_corrida", "password_reset", "sesion_refresh", "ambiente_diario",
    "ingesta_crudo", "meteo_lectura", "modulo", "ndvi_imagen", "phytech_planta_diario",
    "phytech_suelo_horario", "pronostico_clima", "carga_riego", "cronograma", "generacion",
    "turno", "cronograma_version", "lote", "notificacion_correo", "prediccion_entrada",
    "cronograma_ciclo", "cronograma_evento", "cronograma_turno", "riego_registro",
    "carga_riego_turno_dia", "riego_ciclo",
)

# Privilegios de riego_app: estas solo SELECT/INSERT; cronograma_version SELECT/INSERT más
# UPDATE(publicada_at, publicada_por); el resto SELECT/INSERT/UPDATE/DELETE.
SOLO_INSERCION = (
    "auditoria", "cronograma_evento", "prediccion_entrada",
    "riego_ciclo", "cronograma_ciclo", "cronograma_turno",
)
TABLAS_CRUD = tuple(t for t in TABLAS if t not in SOLO_INSERCION and t != "cronograma_version")

# Inmutabilidad por trigger: tabla -> también bloquea TRUNCATE.
INMUTABLES = {
    "auditoria": True,
    "cronograma_evento": True,
    "riego_ciclo": False,
    "cronograma_ciclo": False,
    "cronograma_turno": False,
    "prediccion_entrada": False,
}

# Roles de Supabase que nunca deben ver el esquema (se revocan solo si existen).
ROLES_SUPABASE = ("anon", "authenticated")


def _enum(nombre: str) -> postgresql.ENUM:
    return postgresql.ENUM(*ENUMS[nombre], name=nombre, schema=ESQUEMA, create_type=False)


def upgrade() -> None:
    _crear_enums()
    _crear_tablas()
    _crear_triggers()
    _crear_rol_y_privilegios()
    _habilitar_rls()
    _revocar_publico()


def _crear_enums() -> None:
    bind = op.get_bind()
    for nombre, valores in ENUMS.items():
        postgresql.ENUM(*valores, name=nombre, schema=ESQUEMA).create(bind, checkfirst=False)


def _crear_tablas() -> None:
    op.create_table('empresa',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('codigo', sa.String(length=20), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('activo', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_empresa')),
        sa.UniqueConstraint('codigo', name=op.f('uq_empresa_codigo')),
        schema='riego'
    )
    op.create_table('intento_login',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('tipo', _enum('tipo_intento'), nullable=False),
        sa.Column('username_intentado', sa.String(length=254), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('exito', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_intento_login')),
        schema='riego'
    )
    op.create_index('ix_intento_login_tipo_ip_created_at', 'intento_login', ['tipo', 'ip', 'created_at'], unique=False, schema='riego')
    op.create_index('ix_intento_login_tipo_username_created_at', 'intento_login', ['tipo', 'username_intentado', 'created_at'], unique=False, schema='riego')
    op.create_table('modelo_version',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('version', sa.String(length=40), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('ruta', sa.String(length=500), nullable=True),
        sa.Column('registrado_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_modelo_version')),
        sa.UniqueConstraint('version', name=op.f('uq_modelo_version_version')),
        schema='riego'
    )
    op.create_table('motivo_correccion',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('codigo', sa.String(length=40), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('orden', sa.SmallInteger(), nullable=False),
        sa.Column('activo', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_motivo_correccion')),
        sa.UniqueConstraint('codigo', name=op.f('uq_motivo_correccion_codigo')),
        schema='riego'
    )
    op.create_table('usuario',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('username', sa.String(length=60), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('correo', sa.String(length=254), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('rol', _enum('rol_usuario'), nullable=False),
        sa.Column('activo', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('token_version', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('debe_cambiar_password', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('ultimo_acceso_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('password_cambiada_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('creado_por', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['creado_por'], ['riego.usuario.id'], name=op.f('fk_usuario_creado_por_usuario'), ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_usuario')),
        schema='riego'
    )
    op.create_index(op.f('ix_usuario_creado_por'), 'usuario', ['creado_por'], unique=False, schema='riego')
    op.create_index('uq_usuario_lower_correo', 'usuario', [sa.literal_column('lower(correo)')], unique=True, schema='riego')
    op.create_index('uq_usuario_lower_username', 'usuario', [sa.literal_column('lower(username)')], unique=True, schema='riego')
    op.create_table('auditoria',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('ocurrido_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('usuario_id', sa.BigInteger(), nullable=True),
        sa.Column('username', sa.String(length=60), nullable=True),
        sa.Column('rol', sa.String(length=20), nullable=True),
        sa.Column('accion', sa.String(length=60), nullable=False),
        sa.Column('entidad', sa.String(length=60), nullable=False),
        sa.Column('entidad_id', sa.String(length=60), nullable=True),
        sa.Column('detalle', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(['usuario_id'], ['riego.usuario.id'], name=op.f('fk_auditoria_usuario_id_usuario')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_auditoria')),
        schema='riego'
    )
    op.create_index(op.f('ix_auditoria_accion'), 'auditoria', ['accion'], unique=False, schema='riego')
    op.create_index('ix_auditoria_entidad_entidad_id', 'auditoria', ['entidad', 'entidad_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_auditoria_ocurrido_at'), 'auditoria', ['ocurrido_at'], unique=False, schema='riego')
    op.create_index(op.f('ix_auditoria_usuario_id'), 'auditoria', ['usuario_id'], unique=False, schema='riego')
    op.create_table('fundo',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('empresa_id', sa.BigInteger(), nullable=False),
        sa.Column('codigo', sa.String(length=20), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('zona', sa.String(length=60), nullable=True),
        sa.Column('activo', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['empresa_id'], ['riego.empresa.id'], name=op.f('fk_fundo_empresa_id_empresa')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_fundo')),
        sa.UniqueConstraint('codigo', name=op.f('uq_fundo_codigo')),
        sa.UniqueConstraint('nombre', name=op.f('uq_fundo_nombre')),
        schema='riego'
    )
    op.create_index(op.f('ix_fundo_empresa_id'), 'fundo', ['empresa_id'], unique=False, schema='riego')
    op.create_table('ingesta_corrida',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('fuente', sa.String(length=40), nullable=False),
        sa.Column('disparo', _enum('disparo_ingesta'), nullable=False),
        sa.Column('usuario_id', sa.BigInteger(), nullable=True),
        sa.Column('fecha_programada', sa.Date(), nullable=True),
        sa.Column('desde', sa.Date(), nullable=True),
        sa.Column('hasta', sa.Date(), nullable=True),
        sa.Column('inicio_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('fin_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duracion_ms', sa.Integer(), nullable=True),
        sa.Column('estado', _enum('estado_ingesta'), server_default='en_curso', nullable=False),
        sa.Column('filas_nuevas', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('filas_actualizadas', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('filas_omitidas', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('conflictos', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('errores', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['usuario_id'], ['riego.usuario.id'], name=op.f('fk_ingesta_corrida_usuario_id_usuario')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ingesta_corrida')),
        sa.UniqueConstraint('fuente', 'fecha_programada', name=op.f('uq_ingesta_corrida_fuente_fecha_programada')),
        schema='riego'
    )
    op.create_index('ix_ingesta_corrida_fuente_inicio_at', 'ingesta_corrida', ['fuente', 'inicio_at'], unique=False, schema='riego')
    op.create_index(op.f('ix_ingesta_corrida_usuario_id'), 'ingesta_corrida', ['usuario_id'], unique=False, schema='riego')
    op.create_table('password_reset',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('usuario_id', sa.BigInteger(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('expira_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('usado_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['usuario_id'], ['riego.usuario.id'], name=op.f('fk_password_reset_usuario_id_usuario'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_password_reset')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_password_reset_token_hash')),
        schema='riego'
    )
    op.create_index(op.f('ix_password_reset_usuario_id'), 'password_reset', ['usuario_id'], unique=False, schema='riego')
    op.create_table('sesion_refresh',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('usuario_id', sa.BigInteger(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('familia', sa.Uuid(), nullable=False),
        sa.Column('expira_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('revocado_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reemplazado_por', sa.BigInteger(), nullable=True),
        sa.Column('reemplazado_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ip', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['reemplazado_por'], ['riego.sesion_refresh.id'], name=op.f('fk_sesion_refresh_reemplazado_por_sesion_refresh'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['usuario_id'], ['riego.usuario.id'], name=op.f('fk_sesion_refresh_usuario_id_usuario'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_sesion_refresh')),
        sa.UniqueConstraint('token_hash', name=op.f('uq_sesion_refresh_token_hash')),
        schema='riego'
    )
    op.create_index(op.f('ix_sesion_refresh_familia'), 'sesion_refresh', ['familia'], unique=False, schema='riego')
    op.create_index(op.f('ix_sesion_refresh_reemplazado_por'), 'sesion_refresh', ['reemplazado_por'], unique=False, schema='riego')
    op.create_index(op.f('ix_sesion_refresh_usuario_id'), 'sesion_refresh', ['usuario_id'], unique=False, schema='riego')
    op.create_table('ambiente_diario',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('fundo_id', sa.BigInteger(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('t_media', sa.Double(), nullable=True),
        sa.Column('t_max', sa.Double(), nullable=True),
        sa.Column('t_min', sa.Double(), nullable=True),
        sa.Column('hr_media', sa.Double(), nullable=True),
        sa.Column('hr_min', sa.Double(), nullable=True),
        sa.Column('hr_max', sa.Double(), nullable=True),
        sa.Column('eto_mm', sa.Double(), nullable=True),
        sa.Column('dpv_media', sa.Double(), nullable=True),
        sa.Column('dpv_max', sa.Double(), nullable=True),
        sa.Column('viento_media', sa.Double(), nullable=True),
        sa.Column('lluvia_mm', sa.Double(), nullable=True),
        sa.Column('rad_max', sa.Double(), nullable=True),
        sa.Column('rad_media', sa.Double(), nullable=True),
        sa.Column('horas_t30', sa.Double(), nullable=True),
        sa.Column('meteo_lecturas', sa.Double(), nullable=True),
        sa.Column('hum_15cm_media', sa.Double(), nullable=True),
        sa.Column('hum_30cm_media', sa.Double(), nullable=True),
        sa.Column('hum_45cm_media', sa.Double(), nullable=True),
        sa.Column('hum_60cm_media', sa.Double(), nullable=True),
        sa.Column('hum_75cm_media', sa.Double(), nullable=True),
        sa.Column('hum_90cm_media', sa.Double(), nullable=True),
        sa.Column('hum_zona_radicular_media', sa.Double(), nullable=True),
        sa.Column('hum_linea_estres_media', sa.Double(), nullable=True),
        sa.Column('hum_15cm_cierre', sa.Double(), nullable=True),
        sa.Column('hum_30cm_cierre', sa.Double(), nullable=True),
        sa.Column('hum_45cm_cierre', sa.Double(), nullable=True),
        sa.Column('hum_60cm_cierre', sa.Double(), nullable=True),
        sa.Column('hum_75cm_cierre', sa.Double(), nullable=True),
        sa.Column('hum_90cm_cierre', sa.Double(), nullable=True),
        sa.Column('hum_zona_radicular_cierre', sa.Double(), nullable=True),
        sa.Column('hum_linea_estres_cierre', sa.Double(), nullable=True),
        sa.Column('hum_45cm_rango', sa.Double(), nullable=True),
        sa.Column('hum_60cm_rango', sa.Double(), nullable=True),
        sa.Column('suelo_horas', sa.Double(), nullable=True),
        sa.Column('mds_contraccion_um', sa.Double(), nullable=True),
        sa.Column('crecimiento_tronco_um', sa.Double(), nullable=True),
        sa.Column('estres_planta_ps', sa.Double(), nullable=True),
        sa.Column('ndvi_medio', sa.Double(), nullable=True),
        sa.Column('tiene_meteo', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('tiene_suelo', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('tiene_planta', sa.SmallInteger(), server_default=sa.text('0'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['fundo_id'], ['riego.fundo.id'], name=op.f('fk_ambiente_diario_fundo_id_fundo')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ambiente_diario')),
        sa.UniqueConstraint('fundo_id', 'fecha', name=op.f('uq_ambiente_diario_fundo_id_fecha')),
        schema='riego'
    )
    op.create_table('ingesta_crudo',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('corrida_id', sa.BigInteger(), nullable=False),
        sa.Column('endpoint', sa.String(length=255), nullable=False),
        sa.Column('parametros', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['corrida_id'], ['riego.ingesta_corrida.id'], name=op.f('fk_ingesta_crudo_corrida_id_ingesta_corrida'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ingesta_crudo')),
        schema='riego'
    )
    op.create_index(op.f('ix_ingesta_crudo_corrida_id'), 'ingesta_crudo', ['corrida_id'], unique=False, schema='riego')
    op.create_table('meteo_lectura',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('fundo_id', sa.BigInteger(), nullable=False),
        sa.Column('fecha_hora', sa.DateTime(), nullable=False),
        sa.Column('temp', sa.Double(), nullable=True),
        sa.Column('temp_max', sa.Double(), nullable=True),
        sa.Column('temp_min', sa.Double(), nullable=True),
        sa.Column('hr', sa.Double(), nullable=True),
        sa.Column('hr_max', sa.Double(), nullable=True),
        sa.Column('rad', sa.Double(), nullable=True),
        sa.Column('eto', sa.Double(), nullable=True),
        sa.Column('dpv', sa.Double(), nullable=True),
        sa.Column('viento', sa.Double(), nullable=True),
        sa.Column('lluvia', sa.Double(), nullable=True),
        sa.Column('origen', _enum('origen_meteo'), nullable=False),
        sa.Column('corrida_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['corrida_id'], ['riego.ingesta_corrida.id'], name=op.f('fk_meteo_lectura_corrida_id_ingesta_corrida'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['fundo_id'], ['riego.fundo.id'], name=op.f('fk_meteo_lectura_fundo_id_fundo')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_meteo_lectura')),
        sa.UniqueConstraint('fundo_id', 'fecha_hora', name=op.f('uq_meteo_lectura_fundo_id_fecha_hora')),
        schema='riego'
    )
    op.create_index(op.f('ix_meteo_lectura_corrida_id'), 'meteo_lectura', ['corrida_id'], unique=False, schema='riego')
    op.create_table('modulo',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('fundo_id', sa.BigInteger(), nullable=False),
        sa.Column('codigo', sa.String(length=30), nullable=False),
        sa.Column('nombre', sa.String(length=120), nullable=False),
        sa.Column('area_ha', sa.Double(), nullable=False),
        sa.Column('cultivo', sa.String(length=60), nullable=True),
        sa.Column('variedad', sa.String(length=60), nullable=True),
        sa.Column('campana', sa.String(length=20), nullable=True),
        sa.Column('activo', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['fundo_id'], ['riego.fundo.id'], name=op.f('fk_modulo_fundo_id_fundo')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_modulo')),
        sa.UniqueConstraint('codigo', name=op.f('uq_modulo_codigo')),
        schema='riego'
    )
    op.create_index(op.f('ix_modulo_fundo_id'), 'modulo', ['fundo_id'], unique=False, schema='riego')
    op.create_table('ndvi_imagen',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('fundo_id', sa.BigInteger(), nullable=False),
        sa.Column('image_id', sa.String(length=64), nullable=False),
        sa.Column('area_id', sa.Integer(), nullable=False),
        sa.Column('plot_id', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('no_vegetation', sa.Boolean(), nullable=True),
        sa.Column('clases', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('ndvi_medio', sa.Double(), nullable=True),
        sa.Column('corrida_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['corrida_id'], ['riego.ingesta_corrida.id'], name=op.f('fk_ndvi_imagen_corrida_id_ingesta_corrida'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['fundo_id'], ['riego.fundo.id'], name=op.f('fk_ndvi_imagen_fundo_id_fundo')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_ndvi_imagen')),
        sa.UniqueConstraint('image_id', name=op.f('uq_ndvi_imagen_image_id')),
        schema='riego'
    )
    op.create_index(op.f('ix_ndvi_imagen_corrida_id'), 'ndvi_imagen', ['corrida_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_ndvi_imagen_fecha'), 'ndvi_imagen', ['fecha'], unique=False, schema='riego')
    op.create_index(op.f('ix_ndvi_imagen_fundo_id'), 'ndvi_imagen', ['fundo_id'], unique=False, schema='riego')
    op.create_table('phytech_planta_diario',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('fundo_id', sa.BigInteger(), nullable=False),
        sa.Column('plot_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('mds_contraccion_um', sa.Double(), nullable=True),
        sa.Column('crecimiento_tronco_um', sa.Double(), nullable=True),
        sa.Column('estres_planta_ps', sa.Double(), nullable=True),
        sa.Column('tamano_fruto_mm', sa.Double(), nullable=True),
        sa.Column('crecimiento_fruto_mm', sa.Double(), nullable=True),
        sa.Column('et_mm', sa.Double(), nullable=True),
        sa.Column('lluvia_mm', sa.Double(), nullable=True),
        sa.Column('corrida_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['corrida_id'], ['riego.ingesta_corrida.id'], name=op.f('fk_phytech_planta_diario_corrida_id_ingesta_corrida'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['fundo_id'], ['riego.fundo.id'], name=op.f('fk_phytech_planta_diario_fundo_id_fundo')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_phytech_planta_diario')),
        sa.UniqueConstraint('project_id', 'fecha', name=op.f('uq_phytech_planta_diario_project_id_fecha')),
        schema='riego'
    )
    op.create_index(op.f('ix_phytech_planta_diario_corrida_id'), 'phytech_planta_diario', ['corrida_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_phytech_planta_diario_fundo_id'), 'phytech_planta_diario', ['fundo_id'], unique=False, schema='riego')
    op.create_table('phytech_suelo_horario',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('fundo_id', sa.BigInteger(), nullable=False),
        sa.Column('plot_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('fecha_hora', sa.DateTime(), nullable=False),
        sa.Column('hay_dato', sa.Boolean(), nullable=False),
        sa.Column('hum_15cm', sa.Double(), nullable=True),
        sa.Column('hum_30cm', sa.Double(), nullable=True),
        sa.Column('hum_45cm', sa.Double(), nullable=True),
        sa.Column('hum_60cm', sa.Double(), nullable=True),
        sa.Column('hum_75cm', sa.Double(), nullable=True),
        sa.Column('hum_90cm', sa.Double(), nullable=True),
        sa.Column('temp_15cm', sa.Double(), nullable=True),
        sa.Column('temp_30cm', sa.Double(), nullable=True),
        sa.Column('temp_60cm', sa.Double(), nullable=True),
        sa.Column('temp_90cm', sa.Double(), nullable=True),
        sa.Column('hum_zona_radicular', sa.Double(), nullable=True),
        sa.Column('hum_saturacion', sa.Double(), nullable=True),
        sa.Column('hum_linea_estres', sa.Double(), nullable=True),
        sa.Column('hum_zona_radicular_norm_pct', sa.Double(), nullable=True),
        sa.Column('corrida_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['corrida_id'], ['riego.ingesta_corrida.id'], name=op.f('fk_phytech_suelo_horario_corrida_id_ingesta_corrida'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['fundo_id'], ['riego.fundo.id'], name=op.f('fk_phytech_suelo_horario_fundo_id_fundo')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_phytech_suelo_horario')),
        sa.UniqueConstraint('project_id', 'fecha_hora', name=op.f('uq_phytech_suelo_horario_project_id_fecha_hora')),
        schema='riego'
    )
    op.create_index(op.f('ix_phytech_suelo_horario_corrida_id'), 'phytech_suelo_horario', ['corrida_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_phytech_suelo_horario_fundo_id'), 'phytech_suelo_horario', ['fundo_id'], unique=False, schema='riego')
    op.create_table('pronostico_clima',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('fundo_id', sa.BigInteger(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('capturado_fecha', sa.Date(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('t_max', sa.Double(), nullable=True),
        sa.Column('eto_mm', sa.Double(), nullable=True),
        sa.Column('etc_mm', sa.Double(), nullable=True),
        sa.Column('humedad', sa.Double(), nullable=True),
        sa.Column('corrida_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['corrida_id'], ['riego.ingesta_corrida.id'], name=op.f('fk_pronostico_clima_corrida_id_ingesta_corrida'), ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['fundo_id'], ['riego.fundo.id'], name=op.f('fk_pronostico_clima_fundo_id_fundo')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_pronostico_clima')),
        sa.UniqueConstraint('project_id', 'capturado_fecha', 'fecha', name=op.f('uq_pronostico_clima_project_id_capturado_fecha_fecha')),
        schema='riego'
    )
    op.create_index(op.f('ix_pronostico_clima_corrida_id'), 'pronostico_clima', ['corrida_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_pronostico_clima_fundo_id'), 'pronostico_clima', ['fundo_id'], unique=False, schema='riego')
    op.create_table('carga_riego',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('modulo_id', sa.BigInteger(), nullable=False),
        sa.Column('archivo_nombre', sa.String(length=255), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('tamano_bytes', sa.BigInteger(), nullable=False),
        sa.Column('subido_por', sa.BigInteger(), nullable=True),
        sa.Column('subido_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('estado', _enum('estado_carga'), server_default='previsualizada', nullable=False),
        sa.Column('resumen', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('confirmado_por', sa.BigInteger(), nullable=True),
        sa.Column('confirmado_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['confirmado_por'], ['riego.usuario.id'], name=op.f('fk_carga_riego_confirmado_por_usuario')),
        sa.ForeignKeyConstraint(['modulo_id'], ['riego.modulo.id'], name=op.f('fk_carga_riego_modulo_id_modulo')),
        sa.ForeignKeyConstraint(['subido_por'], ['riego.usuario.id'], name=op.f('fk_carga_riego_subido_por_usuario')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_carga_riego')),
        schema='riego'
    )
    op.create_index(op.f('ix_carga_riego_confirmado_por'), 'carga_riego', ['confirmado_por'], unique=False, schema='riego')
    op.create_index(op.f('ix_carga_riego_modulo_id'), 'carga_riego', ['modulo_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_carga_riego_sha256'), 'carga_riego', ['sha256'], unique=False, schema='riego')
    op.create_index(op.f('ix_carga_riego_subido_por'), 'carga_riego', ['subido_por'], unique=False, schema='riego')
    op.create_table('cronograma',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('modulo_id', sa.BigInteger(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('estado', _enum('estado_cronograma'), server_default='borrador', nullable=False),
        sa.Column('version_publicada_id', sa.BigInteger(), nullable=True),
        sa.Column('borrador_version_id', sa.BigInteger(), nullable=True),
        sa.Column('visto_version_id', sa.BigInteger(), nullable=True),
        sa.Column('visto_programador_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('visto_programador_por', sa.BigInteger(), nullable=True),
        sa.Column('num_publicaciones', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('correccion_solicitada_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('correccion_solicitada_por', sa.BigInteger(), nullable=True),
        sa.Column('correccion_solicitada_motivo', sa.Text(), nullable=True),
        sa.Column('lock_version', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['correccion_solicitada_por'], ['riego.usuario.id'], name=op.f('fk_cronograma_correccion_solicitada_por_usuario')),
        sa.ForeignKeyConstraint(['modulo_id'], ['riego.modulo.id'], name=op.f('fk_cronograma_modulo_id_modulo')),
        sa.ForeignKeyConstraint(['visto_programador_por'], ['riego.usuario.id'], name=op.f('fk_cronograma_visto_programador_por_usuario')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_cronograma')),
        sa.UniqueConstraint('modulo_id', 'fecha', name=op.f('uq_cronograma_modulo_id_fecha')),
        schema='riego'
    )
    op.create_index(op.f('ix_cronograma_borrador_version_id'), 'cronograma', ['borrador_version_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_cronograma_correccion_solicitada_por'), 'cronograma', ['correccion_solicitada_por'], unique=False, schema='riego')
    op.create_index('ix_cronograma_estado', 'cronograma', ['estado'], unique=False, schema='riego')
    op.create_index(op.f('ix_cronograma_version_publicada_id'), 'cronograma', ['version_publicada_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_cronograma_visto_programador_por'), 'cronograma', ['visto_programador_por'], unique=False, schema='riego')
    op.create_index(op.f('ix_cronograma_visto_version_id'), 'cronograma', ['visto_version_id'], unique=False, schema='riego')
    op.create_table('generacion',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('modulo_id', sa.BigInteger(), nullable=False),
        sa.Column('fecha_inicio', sa.Date(), nullable=False),
        sa.Column('dias', sa.SmallInteger(), nullable=False),
        sa.Column('tipo', _enum('tipo_generacion'), nullable=False),
        sa.Column('usuario_id', sa.BigInteger(), nullable=True),
        sa.Column('modelo_version_id', sa.BigInteger(), nullable=True),
        sa.Column('frescura', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('resultado_por_dia', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('duracion_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['modelo_version_id'], ['riego.modelo_version.id'], name=op.f('fk_generacion_modelo_version_id_modelo_version')),
        sa.ForeignKeyConstraint(['modulo_id'], ['riego.modulo.id'], name=op.f('fk_generacion_modulo_id_modulo')),
        sa.ForeignKeyConstraint(['usuario_id'], ['riego.usuario.id'], name=op.f('fk_generacion_usuario_id_usuario')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_generacion')),
        schema='riego'
    )
    op.create_index(op.f('ix_generacion_modelo_version_id'), 'generacion', ['modelo_version_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_generacion_modulo_id'), 'generacion', ['modulo_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_generacion_usuario_id'), 'generacion', ['usuario_id'], unique=False, schema='riego')
    op.create_table('turno',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('modulo_id', sa.BigInteger(), nullable=False),
        sa.Column('codigo', sa.String(length=10), nullable=False),
        sa.Column('orden', sa.SmallInteger(), nullable=False),
        sa.Column('area_ha', sa.Double(), nullable=False),
        sa.Column('valvula_controlador', sa.String(length=20), nullable=False),
        sa.Column('valvula_siga', sa.String(length=20), nullable=True),
        sa.Column('activo', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['modulo_id'], ['riego.modulo.id'], name=op.f('fk_turno_modulo_id_modulo')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_turno')),
        sa.UniqueConstraint('modulo_id', 'codigo', name=op.f('uq_turno_modulo_id_codigo')),
        sa.UniqueConstraint('valvula_controlador', name=op.f('uq_turno_valvula_controlador')),
        schema='riego'
    )
    op.create_table('cronograma_version',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('cronograma_id', sa.BigInteger(), nullable=False),
        sa.Column('numero', sa.Integer(), nullable=False),
        sa.Column('origen', _enum('origen_version'), nullable=False),
        sa.Column('generacion_id', sa.BigInteger(), nullable=True),
        sa.Column('modelo_version_id', sa.BigInteger(), nullable=True),
        sa.Column('basada_en_id', sa.BigInteger(), nullable=True),
        sa.Column('motivo_codigo', sa.String(length=40), nullable=True),
        sa.Column('motivo_comentario', sa.Text(), nullable=True),
        sa.Column('preliminar', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('datos_incompletos', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('creado_por', sa.BigInteger(), nullable=True),
        sa.Column('publicada_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('publicada_por', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['basada_en_id'], ['riego.cronograma_version.id'], name=op.f('fk_cronograma_version_basada_en_id_cronograma_version')),
        sa.ForeignKeyConstraint(['creado_por'], ['riego.usuario.id'], name=op.f('fk_cronograma_version_creado_por_usuario')),
        sa.ForeignKeyConstraint(['cronograma_id'], ['riego.cronograma.id'], name=op.f('fk_cronograma_version_cronograma_id_cronograma')),
        sa.ForeignKeyConstraint(['generacion_id'], ['riego.generacion.id'], name=op.f('fk_cronograma_version_generacion_id_generacion')),
        sa.ForeignKeyConstraint(['modelo_version_id'], ['riego.modelo_version.id'], name=op.f('fk_cronograma_version_modelo_version_id_modelo_version')),
        sa.ForeignKeyConstraint(['motivo_codigo'], ['riego.motivo_correccion.codigo'], name=op.f('fk_cronograma_version_motivo_codigo_motivo_correccion')),
        sa.ForeignKeyConstraint(['publicada_por'], ['riego.usuario.id'], name=op.f('fk_cronograma_version_publicada_por_usuario')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_cronograma_version')),
        sa.UniqueConstraint('cronograma_id', 'numero', name=op.f('uq_cronograma_version_cronograma_id_numero')),
        schema='riego'
    )
    op.create_index(op.f('ix_cronograma_version_basada_en_id'), 'cronograma_version', ['basada_en_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_cronograma_version_creado_por'), 'cronograma_version', ['creado_por'], unique=False, schema='riego')
    op.create_index(op.f('ix_cronograma_version_generacion_id'), 'cronograma_version', ['generacion_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_cronograma_version_modelo_version_id'), 'cronograma_version', ['modelo_version_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_cronograma_version_motivo_codigo'), 'cronograma_version', ['motivo_codigo'], unique=False, schema='riego')
    op.create_index(op.f('ix_cronograma_version_publicada_por'), 'cronograma_version', ['publicada_por'], unique=False, schema='riego')
    op.create_table('lote',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('turno_id', sa.BigInteger(), nullable=False),
        sa.Column('codigo', sa.String(length=10), nullable=False),
        sa.Column('area_ha', sa.Double(), nullable=False),
        sa.Column('campana', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['turno_id'], ['riego.turno.id'], name=op.f('fk_lote_turno_id_turno')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_lote')),
        sa.UniqueConstraint('turno_id', 'codigo', 'campana', name=op.f('uq_lote_turno_id_codigo_campana')),
        schema='riego'
    )
    op.create_table('notificacion_correo',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('tipo', sa.String(length=40), nullable=False),
        sa.Column('usuario_id', sa.BigInteger(), nullable=True),
        sa.Column('cronograma_id', sa.BigInteger(), nullable=True),
        sa.Column('rol_destino', _enum('rol_usuario'), nullable=True),
        sa.Column('destinatarios', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('asunto', sa.String(length=255), nullable=False),
        sa.Column('contexto', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('estado', _enum('estado_correo'), server_default='pendiente', nullable=False),
        sa.Column('intentos', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('proximo_intento_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('bloqueado_hasta', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ultimo_error', sa.Text(), nullable=True),
        sa.Column('enviado_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['cronograma_id'], ['riego.cronograma.id'], name=op.f('fk_notificacion_correo_cronograma_id_cronograma')),
        sa.ForeignKeyConstraint(['usuario_id'], ['riego.usuario.id'], name=op.f('fk_notificacion_correo_usuario_id_usuario'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_notificacion_correo')),
        schema='riego'
    )
    op.create_index(op.f('ix_notificacion_correo_cronograma_id'), 'notificacion_correo', ['cronograma_id'], unique=False, schema='riego')
    op.create_index('ix_notificacion_correo_estado_proximo_intento_at', 'notificacion_correo', ['estado', 'proximo_intento_at'], unique=False, schema='riego')
    op.create_index(op.f('ix_notificacion_correo_usuario_id'), 'notificacion_correo', ['usuario_id'], unique=False, schema='riego')
    op.create_table('prediccion_entrada',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('generacion_id', sa.BigInteger(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('turno_id', sa.BigInteger(), nullable=False),
        sa.Column('modelo_version_id', sa.BigInteger(), nullable=True),
        sa.Column('features_turno', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('features_ciclo', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('alternativas_n', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('origen_riego_d1', _enum('origen_riego_d1'), nullable=False),
        sa.Column('fuentes_hasta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['generacion_id'], ['riego.generacion.id'], name=op.f('fk_prediccion_entrada_generacion_id_generacion')),
        sa.ForeignKeyConstraint(['modelo_version_id'], ['riego.modelo_version.id'], name=op.f('fk_prediccion_entrada_modelo_version_id_modelo_version')),
        sa.ForeignKeyConstraint(['turno_id'], ['riego.turno.id'], name=op.f('fk_prediccion_entrada_turno_id_turno')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_prediccion_entrada')),
        sa.UniqueConstraint('generacion_id', 'fecha', 'turno_id', name=op.f('uq_prediccion_entrada_generacion_id_fecha_turno_id')),
        schema='riego'
    )
    op.create_index(op.f('ix_prediccion_entrada_modelo_version_id'), 'prediccion_entrada', ['modelo_version_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_prediccion_entrada_turno_id'), 'prediccion_entrada', ['turno_id'], unique=False, schema='riego')
    op.create_table('cronograma_ciclo',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('version_id', sa.BigInteger(), nullable=False),
        sa.Column('turno_id', sa.BigInteger(), nullable=False),
        sa.Column('ciclo', sa.SmallInteger(), nullable=False),
        sa.Column('riego_m3ha', sa.Double(), nullable=False),
        sa.Column('riego_m3', sa.Double(), nullable=False),
        sa.Column('duracion_min', sa.Double(), nullable=False),
        sa.Column('inicio_min', sa.Double(), nullable=False),
        sa.Column('fin_min', sa.Double(), nullable=False),
        sa.Column('hora_inicio', sa.String(length=5), nullable=False),
        sa.Column('hora_fin', sa.String(length=5), nullable=False),
        sa.Column('fin_dia_siguiente', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('m3ha_p10', sa.Double(), nullable=True),
        sa.Column('m3ha_p90', sa.Double(), nullable=True),
        sa.Column('duracion_p10', sa.Double(), nullable=True),
        sa.Column('duracion_p90', sa.Double(), nullable=True),
        sa.Column('inicio_desde_min', sa.Double(), nullable=True),
        sa.Column('inicio_hasta_min', sa.Double(), nullable=True),
        sa.Column('ciclo_modelo', sa.SmallInteger(), nullable=True),
        sa.Column('duracion_manual', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('campos_editados', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['turno_id'], ['riego.turno.id'], name=op.f('fk_cronograma_ciclo_turno_id_turno')),
        sa.ForeignKeyConstraint(['version_id'], ['riego.cronograma_version.id'], name=op.f('fk_cronograma_ciclo_version_id_cronograma_version')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_cronograma_ciclo')),
        sa.UniqueConstraint('version_id', 'turno_id', 'ciclo', name=op.f('uq_cronograma_ciclo_version_id_turno_id_ciclo')),
        schema='riego'
    )
    op.create_index(op.f('ix_cronograma_ciclo_turno_id'), 'cronograma_ciclo', ['turno_id'], unique=False, schema='riego')
    op.create_table('cronograma_evento',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('cronograma_id', sa.BigInteger(), nullable=False),
        sa.Column('version_id', sa.BigInteger(), nullable=True),
        sa.Column('tipo', _enum('tipo_evento_cronograma'), nullable=False),
        sa.Column('usuario_id', sa.BigInteger(), nullable=True),
        sa.Column('ocurrido_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('motivo_codigo', sa.String(length=40), nullable=True),
        sa.Column('comentario', sa.Text(), nullable=True),
        sa.Column('detalle', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(['cronograma_id'], ['riego.cronograma.id'], name=op.f('fk_cronograma_evento_cronograma_id_cronograma')),
        sa.ForeignKeyConstraint(['motivo_codigo'], ['riego.motivo_correccion.codigo'], name=op.f('fk_cronograma_evento_motivo_codigo_motivo_correccion')),
        sa.ForeignKeyConstraint(['usuario_id'], ['riego.usuario.id'], name=op.f('fk_cronograma_evento_usuario_id_usuario')),
        sa.ForeignKeyConstraint(['version_id'], ['riego.cronograma_version.id'], name=op.f('fk_cronograma_evento_version_id_cronograma_version')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_cronograma_evento')),
        schema='riego'
    )
    op.create_index('ix_cronograma_evento_cronograma_id_ocurrido_at', 'cronograma_evento', ['cronograma_id', 'ocurrido_at'], unique=False, schema='riego')
    op.create_index(op.f('ix_cronograma_evento_motivo_codigo'), 'cronograma_evento', ['motivo_codigo'], unique=False, schema='riego')
    op.create_index(op.f('ix_cronograma_evento_usuario_id'), 'cronograma_evento', ['usuario_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_cronograma_evento_version_id'), 'cronograma_evento', ['version_id'], unique=False, schema='riego')
    op.create_table('cronograma_turno',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('version_id', sa.BigInteger(), nullable=False),
        sa.Column('turno_id', sa.BigInteger(), nullable=False),
        sa.Column('n_ciclos', sa.SmallInteger(), nullable=False),
        sa.Column('n_ciclos_modelo', sa.SmallInteger(), nullable=True),
        sa.Column('factor_min_por_m3ha', sa.Double(), nullable=True),
        sa.Column('area_ha', sa.Double(), nullable=False),
        sa.Column('caudal_m3h', sa.Double(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['turno_id'], ['riego.turno.id'], name=op.f('fk_cronograma_turno_turno_id_turno')),
        sa.ForeignKeyConstraint(['version_id'], ['riego.cronograma_version.id'], name=op.f('fk_cronograma_turno_version_id_cronograma_version')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_cronograma_turno')),
        sa.UniqueConstraint('version_id', 'turno_id', name=op.f('uq_cronograma_turno_version_id_turno_id')),
        schema='riego'
    )
    op.create_index(op.f('ix_cronograma_turno_turno_id'), 'cronograma_turno', ['turno_id'], unique=False, schema='riego')
    op.create_table('riego_registro',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('modulo_id', sa.BigInteger(), nullable=False),
        sa.Column('turno_id', sa.BigInteger(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('vigente', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('estado', _enum('estado_riego'), nullable=False),
        sa.Column('origen', _enum('origen_riego'), nullable=False),
        sa.Column('sin_riego', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('contenido_sha256', sa.String(length=64), nullable=False),
        sa.Column('cronograma_version_id', sa.BigInteger(), nullable=True),
        sa.Column('carga_id', sa.BigInteger(), nullable=True),
        sa.Column('basado_en_id', sa.BigInteger(), nullable=True),
        sa.Column('motivo', sa.String(length=255), nullable=True),
        sa.Column('comentario', sa.Text(), nullable=True),
        sa.Column('creado_por', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['basado_en_id'], ['riego.riego_registro.id'], name=op.f('fk_riego_registro_basado_en_id_riego_registro')),
        sa.ForeignKeyConstraint(['carga_id'], ['riego.carga_riego.id'], name=op.f('fk_riego_registro_carga_id_carga_riego')),
        sa.ForeignKeyConstraint(['creado_por'], ['riego.usuario.id'], name=op.f('fk_riego_registro_creado_por_usuario')),
        sa.ForeignKeyConstraint(['cronograma_version_id'], ['riego.cronograma_version.id'], name=op.f('fk_riego_registro_cronograma_version_id_cronograma_version')),
        sa.ForeignKeyConstraint(['modulo_id'], ['riego.modulo.id'], name=op.f('fk_riego_registro_modulo_id_modulo')),
        sa.ForeignKeyConstraint(['turno_id'], ['riego.turno.id'], name=op.f('fk_riego_registro_turno_id_turno')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_riego_registro')),
        sa.UniqueConstraint('turno_id', 'fecha', 'version', name=op.f('uq_riego_registro_turno_id_fecha_version')),
        schema='riego'
    )
    op.create_index(op.f('ix_riego_registro_basado_en_id'), 'riego_registro', ['basado_en_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_riego_registro_carga_id'), 'riego_registro', ['carga_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_riego_registro_creado_por'), 'riego_registro', ['creado_por'], unique=False, schema='riego')
    op.create_index(op.f('ix_riego_registro_cronograma_version_id'), 'riego_registro', ['cronograma_version_id'], unique=False, schema='riego')
    op.create_index('ix_riego_registro_modulo_id_fecha', 'riego_registro', ['modulo_id', 'fecha'], unique=False, schema='riego')
    op.create_index('uq_riego_registro_turno_id_fecha_vigente', 'riego_registro', ['turno_id', 'fecha'], unique=True, schema='riego', postgresql_where=sa.text('vigente'))
    op.create_table('carga_riego_turno_dia',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('carga_id', sa.BigInteger(), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('turno_id', sa.BigInteger(), nullable=True),
        sa.Column('turno_codigo', sa.String(length=20), nullable=True),
        sa.Column('resultado', _enum('resultado_carga'), nullable=False),
        sa.Column('vigente_id_comparado', sa.BigInteger(), nullable=True),
        sa.Column('ciclos', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('mensajes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('aplicar', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['carga_id'], ['riego.carga_riego.id'], name=op.f('fk_carga_riego_turno_dia_carga_id_carga_riego'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['turno_id'], ['riego.turno.id'], name=op.f('fk_carga_riego_turno_dia_turno_id_turno')),
        sa.ForeignKeyConstraint(['vigente_id_comparado'], ['riego.riego_registro.id'], name=op.f('fk_carga_riego_turno_dia_vigente_id_comparado_riego_registro')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_carga_riego_turno_dia')),
        schema='riego'
    )
    op.create_index('ix_carga_riego_turno_dia_carga_id_fecha_turno_id', 'carga_riego_turno_dia', ['carga_id', 'fecha', 'turno_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_carga_riego_turno_dia_turno_id'), 'carga_riego_turno_dia', ['turno_id'], unique=False, schema='riego')
    op.create_index(op.f('ix_carga_riego_turno_dia_vigente_id_comparado'), 'carga_riego_turno_dia', ['vigente_id_comparado'], unique=False, schema='riego')
    op.create_table('riego_ciclo',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column('registro_id', sa.BigInteger(), nullable=False),
        sa.Column('inicio_min', sa.Double(), nullable=False),
        sa.Column('fin_min', sa.Double(), nullable=False),
        sa.Column('duracion_min', sa.Double(), nullable=False),
        sa.Column('riego_m3', sa.Double(), nullable=True),
        sa.Column('riego_m3ha', sa.Double(), nullable=True),
        sa.Column('area_ha', sa.Double(), nullable=True),
        sa.Column('valvula', sa.String(length=20), nullable=True),
        sa.Column('hora_inicio', sa.String(length=5), nullable=False),
        sa.Column('hora_fin', sa.String(length=5), nullable=False),
        sa.Column('fin_dia_siguiente', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['registro_id'], ['riego.riego_registro.id'], name=op.f('fk_riego_ciclo_registro_id_riego_registro')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_riego_ciclo')),
        sa.UniqueConstraint('registro_id', 'inicio_min', name=op.f('uq_riego_ciclo_registro_id_inicio_min')),
        schema='riego'
    )

    # Claves foráneas circulares cronograma -> cronograma_version
    op.create_foreign_key(op.f('fk_cronograma_borrador_version_id_cronograma_version'), 'cronograma', 'cronograma_version', ['borrador_version_id'], ['id'],
                          source_schema='riego', referent_schema='riego')
    op.create_foreign_key(op.f('fk_cronograma_version_publicada_id_cronograma_version'), 'cronograma', 'cronograma_version', ['version_publicada_id'], ['id'],
                          source_schema='riego', referent_schema='riego')
    op.create_foreign_key(op.f('fk_cronograma_visto_version_id_cronograma_version'), 'cronograma', 'cronograma_version', ['visto_version_id'], ['id'],
                          source_schema='riego', referent_schema='riego')


def _crear_triggers() -> None:
    op.execute(
        f"""
        CREATE FUNCTION {ESQUEMA}.rechazar_modificacion() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            RAISE EXCEPTION 'La tabla %.% es de solo inserción: no se permite %',
                TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'insufficient_privilege';
        END;
        $$
        """
    )
    for tabla, truncate in INMUTABLES.items():
        op.execute(
            f"CREATE TRIGGER tg_{tabla}_inmutable BEFORE UPDATE OR DELETE ON {ESQUEMA}.{tabla} "
            f"FOR EACH ROW EXECUTE FUNCTION {ESQUEMA}.rechazar_modificacion()"
        )
        if truncate:
            op.execute(
                f"CREATE TRIGGER tg_{tabla}_sin_truncate BEFORE TRUNCATE ON {ESQUEMA}.{tabla} "
                f"FOR EACH STATEMENT EXECUTE FUNCTION {ESQUEMA}.rechazar_modificacion()"
            )

    # cronograma_version: inmutable salvo fijar publicada_at/publicada_por una sola vez.
    op.execute(
        f"""
        CREATE FUNCTION {ESQUEMA}.cronograma_version_inmutable() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Las versiones de cronograma no se pueden borrar'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
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
        END;
        $$
        """
    )
    op.execute(
        f"CREATE TRIGGER tg_cronograma_version_inmutable BEFORE UPDATE OR DELETE "
        f"ON {ESQUEMA}.cronograma_version FOR EACH ROW "
        f"EXECUTE FUNCTION {ESQUEMA}.cronograma_version_inmutable()"
    )
    op.execute(
        f"REVOKE EXECUTE ON FUNCTION {ESQUEMA}.rechazar_modificacion(), "
        f"{ESQUEMA}.cronograma_version_inmutable() FROM PUBLIC"
    )


def _crear_rol_y_privilegios() -> None:
    # Rol de la aplicación: sin LOGIN hasta `configurar-rol-app`; nunca dueño ni BYPASSRLS.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROL_APP}') THEN
                CREATE ROLE {ROL_APP} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA {ESQUEMA} TO {ROL_APP}")
    crud = ", ".join(f"{ESQUEMA}.{t}" for t in TABLAS_CRUD)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {crud} TO {ROL_APP}")
    insercion = ", ".join(f"{ESQUEMA}.{t}" for t in SOLO_INSERCION)
    op.execute(f"GRANT SELECT, INSERT ON {insercion} TO {ROL_APP}")
    op.execute(f"GRANT SELECT, INSERT ON {ESQUEMA}.cronograma_version TO {ROL_APP}")
    op.execute(
        f"GRANT UPDATE (publicada_at, publicada_por) ON {ESQUEMA}.cronograma_version TO {ROL_APP}"
    )
    op.execute(f"GRANT SELECT ON {ESQUEMA}.alembic_version TO {ROL_APP}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {ESQUEMA} TO {ROL_APP}")


def _habilitar_rls() -> None:
    # Una única política permisiva por tabla, solo para riego_app. El dueño (migraciones) no
    # está sujeto a RLS; anon/authenticated/PUBLIC no tienen política (no ven nada).
    for tabla in (*TABLAS, "alembic_version"):
        op.execute(f"ALTER TABLE {ESQUEMA}.{tabla} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {ROL_APP}_acceso ON {ESQUEMA}.{tabla} AS PERMISSIVE FOR ALL "
            f"TO {ROL_APP} USING (true) WITH CHECK (true)"
        )


def _revocar_publico() -> None:
    roles = ", ".join(f"'{r}'" for r in ROLES_SUPABASE)
    op.execute(
        f"""
        DO $$
        DECLARE
            rol text;
        BEGIN
            FOREACH rol IN ARRAY ARRAY['public', {roles}] LOOP
                IF rol = 'public' OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname = rol) THEN
                    EXECUTE format('REVOKE ALL ON SCHEMA {ESQUEMA} FROM %s', rol);
                    EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA {ESQUEMA} FROM %s', rol);
                    EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA {ESQUEMA} FROM %s', rol);
                    EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA {ESQUEMA} FROM %s', rol);
                    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA {ESQUEMA} '
                                   'REVOKE ALL ON TABLES FROM %s', rol);
                    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA {ESQUEMA} '
                                   'REVOKE ALL ON SEQUENCES FROM %s', rol);
                    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA {ESQUEMA} '
                                   'REVOKE ALL ON FUNCTIONS FROM %s', rol);
                END IF;
            END LOOP;
        END
        $$
        """
    )


def downgrade() -> None:
    # Se conservan el esquema y riego.alembic_version (Alembic borra su fila al final) y el rol
    # riego_app (es global del servidor y puede tener privilegios en otras bases).
    for tabla in reversed(TABLAS):
        op.execute(f"DROP TABLE IF EXISTS {ESQUEMA}.{tabla} CASCADE")
    op.execute(f"DROP FUNCTION IF EXISTS {ESQUEMA}.rechazar_modificacion()")
    op.execute(f"DROP FUNCTION IF EXISTS {ESQUEMA}.cronograma_version_inmutable()")
    for nombre in ENUMS:
        op.execute(f"DROP TYPE IF EXISTS {ESQUEMA}.{nombre}")
    op.execute(f"DROP POLICY IF EXISTS {ROL_APP}_acceso ON {ESQUEMA}.alembic_version")
    op.execute(f"ALTER TABLE {ESQUEMA}.alembic_version DISABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{ROL_APP}') THEN
                REVOKE ALL ON {ESQUEMA}.alembic_version FROM {ROL_APP};
                REVOKE ALL ON SCHEMA {ESQUEMA} FROM {ROL_APP};
            END IF;
        END
        $$
        """
    )
