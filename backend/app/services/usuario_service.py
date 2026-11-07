"""Gestión de usuarios (solo admin) y alta del primer administrador desde la CLI.

Reglas: un admin no puede desactivarse a sí mismo y siempre debe quedar al menos un admin activo.
Desactivar, cambiar el rol o asignar una contraseña temporal invalida de inmediato los accesos
del usuario (``token_version + 1`` y revocación de sus sesiones).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errores import Conflicto, NoEncontrado, SolicitudInvalida
from app.core.security import hash_password
from app.core.tiempo import ahora_utc
from app.models import Usuario
from app.models.enums import RolUsuario
from app.repositories import usuarios as repo_usuarios
from app.services import auditoria_service as auditoria
from app.services.auth_service import invalidar_accesos, validar_politica
from app.services.contexto import ContextoPeticion

MENSAJE_USUARIO_DUPLICADO = "Ya existe un usuario con ese nombre de usuario."
MENSAJE_CORREO_DUPLICADO = "Ya existe un usuario con ese correo."
MENSAJE_ULTIMO_ADMIN = "Debe quedar al menos un administrador activo."


@dataclass(frozen=True)
class DatosUsuarioNuevo:
    username: str
    nombre: str
    correo: str
    rol: RolUsuario
    password: str


def obtener(db: Session, usuario_id: int, *, bloquear: bool = False) -> Usuario:
    usuario = repo_usuarios.por_id(db, usuario_id, bloquear=bloquear)
    if usuario is None:
        raise NoEncontrado("Usuario no encontrado")
    return usuario


def _verificar_unicos(db: Session, *, username: str | None = None, correo: str | None = None,
                      excluir_id: int | None = None) -> None:
    if username is not None:
        existente = repo_usuarios.por_username(db, username)
        if existente is not None and existente.id != excluir_id:
            raise Conflicto(MENSAJE_USUARIO_DUPLICADO)
    if correo is not None:
        existente = repo_usuarios.por_correo(db, correo)
        if existente is not None and existente.id != excluir_id:
            raise Conflicto(MENSAJE_CORREO_DUPLICADO)


def crear(
    db: Session,
    datos: DatosUsuarioNuevo,
    *,
    actor: Usuario | None,
    contexto: ContextoPeticion,
    debe_cambiar_password: bool = True,
) -> Usuario:
    """Alta de usuario. Con ``actor=None`` la auditoría registra al "sistema" (CLI)."""
    username = datos.username.strip().lower()
    correo = datos.correo.strip().lower()
    validar_politica(datos.password, username)
    _verificar_unicos(db, username=username, correo=correo)
    usuario = Usuario(
        username=username,
        nombre=datos.nombre.strip(),
        correo=correo,
        rol=datos.rol,
        password_hash=hash_password(datos.password),
        activo=True,
        token_version=0,
        debe_cambiar_password=debe_cambiar_password,
        password_cambiada_at=None if debe_cambiar_password else ahora_utc(),
        creado_por=actor.id if actor else None,
    )
    db.add(usuario)
    try:
        db.flush()
    except IntegrityError:
        # Carrera con otra alta simultánea: los índices únicos (lower) tienen la última palabra.
        db.rollback()
        raise Conflicto("Ya existe un usuario con ese nombre de usuario o correo.") from None
    auditoria.registrar(
        db,
        accion=auditoria.USUARIO_CREADO,
        entidad=auditoria.ENTIDAD_USUARIO,
        entidad_id=usuario.id,
        actor=actor,
        actor_username=None if actor else auditoria.ACTOR_SISTEMA,
        detalle={"despues": auditoria.instantanea_usuario(usuario)},
        contexto=contexto,
    )
    db.commit()
    return usuario


def _quedaria_sin_admin(usuario: Usuario, rol: RolUsuario, activo: bool, admins_activos: list[int]) -> bool:
    deja_de_ser_admin = usuario.rol == RolUsuario.admin and usuario.activo and (
        rol != RolUsuario.admin or not activo
    )
    return deja_de_ser_admin and not [i for i in admins_activos if i != usuario.id]


def editar(
    db: Session,
    usuario_id: int,
    cambios: dict,
    *,
    actor: Usuario,
    contexto: ContextoPeticion,
) -> Usuario:
    """Aplica ``cambios`` (nombre, correo, rol, activo; solo las claves enviadas)."""
    # Primero los admin activos (siempre en el mismo orden) y luego el usuario: evita carreras que
    # dejen el sistema sin admin y bloqueos cruzados entre dos ediciones simultáneas.
    admins_activos = (
        repo_usuarios.admins_activos_bloqueados(db) if {"rol", "activo"} & cambios.keys() else []
    )
    usuario = obtener(db, usuario_id, bloquear=True)
    antes = auditoria.instantanea_usuario(usuario)

    nombre = cambios.get("nombre")
    correo = cambios.get("correo")
    rol = cambios.get("rol", usuario.rol) or usuario.rol
    activo = cambios.get("activo", usuario.activo)
    if activo is None:
        activo = usuario.activo

    if usuario.id == actor.id and not activo:
        raise SolicitudInvalida("No puedes desactivar tu propio usuario.")
    if _quedaria_sin_admin(usuario, rol, activo, admins_activos):
        raise SolicitudInvalida(MENSAJE_ULTIMO_ADMIN)
    if correo is not None:
        correo = correo.strip().lower()
        _verificar_unicos(db, correo=correo, excluir_id=usuario.id)
        usuario.correo = correo
    if nombre is not None:
        usuario.nombre = nombre.strip()
    rol_cambia = rol != usuario.rol
    activo_cambia = activo != usuario.activo
    usuario.rol = rol
    usuario.activo = activo
    if rol_cambia or (activo_cambia and not activo):
        invalidar_accesos(db, usuario)

    despues = auditoria.instantanea_usuario(usuario)

    def _auditar(accion: str, campos: tuple[str, ...]) -> None:
        cambio = auditoria.diferencias(
            {c: antes[c] for c in campos}, {c: despues[c] for c in campos}
        )
        if cambio["despues"]:
            auditoria.registrar(
                db, accion=accion, entidad=auditoria.ENTIDAD_USUARIO, entidad_id=usuario.id,
                actor=actor, detalle=cambio, contexto=contexto,
            )

    _auditar(auditoria.USUARIO_EDITADO, ("nombre", "correo"))
    if rol_cambia:
        _auditar(auditoria.ROL_CAMBIADO, ("rol",))
    if activo_cambia:
        _auditar(auditoria.USUARIO_ACTIVADO if activo else auditoria.USUARIO_DESACTIVADO, ("activo",))
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflicto(MENSAJE_CORREO_DUPLICADO) from None
    db.commit()
    return usuario


def asignar_password_temporal(
    db: Session, usuario_id: int, password: str, *, actor: Usuario, contexto: ContextoPeticion
) -> Usuario:
    usuario = obtener(db, usuario_id, bloquear=True)
    validar_politica(password, usuario.username)
    antes = auditoria.instantanea_usuario(usuario)
    usuario.password_hash = hash_password(password)
    usuario.debe_cambiar_password = True
    invalidar_accesos(db, usuario)
    auditoria.registrar(
        db,
        accion=auditoria.PASSWORD_TEMPORAL_ASIGNADO,
        entidad=auditoria.ENTIDAD_USUARIO,
        entidad_id=usuario.id,
        actor=actor,
        detalle=auditoria.diferencias(antes, auditoria.instantanea_usuario(usuario)),
        contexto=contexto,
    )
    db.commit()
    return usuario
