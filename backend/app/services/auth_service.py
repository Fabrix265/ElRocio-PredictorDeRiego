"""Autenticación: login, refresh rotativo, logout, recuperación y cambio de contraseña (§7).

- Refresh token opaco en cookie ``rt``; en la BD solo su SHA-256 (``sesion_refresh``). Cada uso lo
  rota dentro de su ``familia``. Reusar uno ya reemplazado:
  - dentro de :data:`GRACIA_REUSO` (respuesta perdida, o dos pestañas sin el candado del
    frontend) se entrega **una sola vez** un sucesor nuevo y se revocan las demás hojas activas
    de la familia (nunca hay más de una);
  - un segundo reuso, o uno fuera de ese plazo, se considera robo y se revoca toda la familia;
  - usar un token revocado mientras su familia sigue activa (la hoja que la gracia dejó sin
    efecto) también revoca la familia.
  La sesión se desliza 7 días con cada uso, con un tope de :data:`TOPE_SESION` desde el login.
- Desactivar, cambiar rol o contraseña: ``token_version + 1`` (invalida los access token),
  revocación de todas las sesiones y de los enlaces de recuperación pendientes.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import CredencialesInvalidas, DatosInvalidos, NoAutenticado, SolicitudInvalida
from app.core.security import (
    crear_access_token,
    errores_politica_password,
    generar_token_opaco,
    hash_password,
    hash_token,
    necesita_rehash,
    verificar_password,
    verificar_password_ficticia,
)
from app.core.tiempo import ahora_utc
from app.models import PasswordReset, SesionRefresh, Usuario
from app.models.enums import TipoIntento
from app.repositories import usuarios as repo_usuarios
from app.services import auditoria_service as auditoria
from app.services import correo_service, rate_limit
from app.services.contexto import ContextoPeticion

logger = logging.getLogger(__name__)

GRACIA_REUSO = timedelta(seconds=30)
TOPE_SESION = timedelta(days=30)  # duración máxima de una familia desde el login
RETENCION_LIMPIEZA = timedelta(days=30)
MENSAJE_ENLACE_INVALIDO = "El enlace no es válido o ya venció."
ASUNTO_RECUPERACION = "Restablece tu contraseña - Sistema de Plan de Riego"


@dataclass(frozen=True)
class SesionEmitida:
    usuario: Usuario
    access_token: str
    expires_in: int
    refresh_token: str


def validar_politica(password: str, username: str | None) -> None:
    errores = errores_politica_password(password, username)
    if errores:
        raise DatosInvalidos(" ".join(errores))


# --- Sesiones -----------------------------------------------------------------

def _vencimiento(db: Session, familia: uuid.UUID | None) -> datetime:
    """Vencimiento de una sesión nueva: 7 días desde ahora, sin pasar el tope de la familia."""
    vence = ahora_utc() + timedelta(days=settings.refresh_token_days)
    if familia is not None:
        inicio = db.scalar(
            select(func.min(SesionRefresh.created_at)).where(SesionRefresh.familia == familia)
        )
        if inicio is not None:
            vence = min(vence, inicio + TOPE_SESION)
    return vence


def _nueva_sesion_refresh(
    db: Session, usuario: Usuario, contexto: ContextoPeticion, familia: uuid.UUID | None = None
) -> tuple[SesionRefresh, str]:
    token = generar_token_opaco()
    sesion = SesionRefresh(
        usuario_id=usuario.id,
        token_hash=hash_token(token),
        familia=familia or uuid.uuid4(),
        expira_at=_vencimiento(db, familia),
        created_at=ahora_utc(),  # reloj de la app (base del tope de la familia)
        ip=contexto.ip,
        user_agent=contexto.user_agent,
    )
    db.add(sesion)
    db.flush()
    return sesion, token


def emitir_sesion(
    db: Session, usuario: Usuario, contexto: ContextoPeticion, familia: uuid.UUID | None = None
) -> SesionEmitida:
    _, refresh = _nueva_sesion_refresh(db, usuario, contexto, familia)
    access, vigencia = crear_access_token(usuario.id, usuario.token_version)
    return SesionEmitida(usuario, access, vigencia, refresh)


def revocar_sesiones(db: Session, usuario_id: int) -> None:
    db.execute(
        update(SesionRefresh)
        .where(SesionRefresh.usuario_id == usuario_id, SesionRefresh.revocado_at.is_(None))
        .values(revocado_at=ahora_utc())
        .execution_options(synchronize_session=False)
    )


def _revocar_familia(db: Session, familia: uuid.UUID) -> None:
    db.execute(
        update(SesionRefresh)
        .where(SesionRefresh.familia == familia, SesionRefresh.revocado_at.is_(None))
        .values(revocado_at=ahora_utc())
        .execution_options(synchronize_session=False)
    )


def _familia_activa(db: Session, familia: uuid.UUID) -> bool:
    return bool(db.scalar(select(exists().where(
        SesionRefresh.familia == familia,
        SesionRefresh.revocado_at.is_(None),
        SesionRefresh.expira_at > ahora_utc(),
    ))))


def _revocar_hojas(db: Session, familia: uuid.UUID) -> None:
    """Revoca las sesiones vigentes (no reemplazadas) de la familia."""
    db.execute(
        update(SesionRefresh)
        .where(
            SesionRefresh.familia == familia,
            SesionRefresh.revocado_at.is_(None),
            SesionRefresh.reemplazado_por.is_(None),
        )
        .values(revocado_at=ahora_utc())
        .execution_options(synchronize_session=False)
    )


def invalidar_resets(db: Session, usuario_id: int) -> None:
    """Deja sin efecto los enlaces de recuperación pendientes del usuario."""
    db.execute(
        update(PasswordReset)
        .where(PasswordReset.usuario_id == usuario_id, PasswordReset.usado_at.is_(None))
        .values(usado_at=ahora_utc())
        .execution_options(synchronize_session=False)
    )


def invalidar_accesos(db: Session, usuario: Usuario) -> None:
    """``token_version + 1``, revocación de todas sus sesiones y de los enlaces de recuperación
    pendientes (efecto inmediato)."""
    usuario.token_version = (usuario.token_version or 0) + 1
    revocar_sesiones(db, usuario.id)
    invalidar_resets(db, usuario.id)


# --- Login --------------------------------------------------------------------

def login(db: Session, username: str, password: str, contexto: ContextoPeticion) -> SesionEmitida:
    # Se registra (como fallo) antes de verificar: los intentos simultáneos se cuentan entre sí.
    intento = rate_limit.reservar(db, TipoIntento.login, usuario=username, ip=contexto.ip)

    usuario = repo_usuarios.por_username(db, username) if username.strip() else None
    if usuario is None:
        verificar_password_ficticia(password)  # mismo tiempo de respuesta
        password_ok = False
    else:
        password_ok = verificar_password(password, usuario.password_hash)

    if usuario is None or not password_ok or not usuario.activo:
        # Mismo mensaje en todos los casos; el motivo solo queda en la auditoría.
        if usuario is None:
            motivo = "usuario_inexistente"
        elif not password_ok:
            motivo = "password_incorrecta"
        else:
            motivo = "usuario_inactivo"
        # Nunca se guarda el texto escrito si el usuario no existe (podría ser una contraseña);
        # si existe, el intento queda a su nombre (el filtro por usuario lo muestra).
        auditoria.registrar(
            db,
            accion=auditoria.LOGIN_FALLIDO,
            entidad=auditoria.ENTIDAD_USUARIO,
            entidad_id=usuario.id if usuario else None,
            actor=usuario,
            detalle={"motivo": motivo},
            contexto=contexto,
        )
        db.commit()
        raise CredencialesInvalidas()

    if necesita_rehash(usuario.password_hash):
        usuario.password_hash = hash_password(password)
    usuario.ultimo_acceso_at = ahora_utc()
    rate_limit.marcar_exito(db, intento)
    sesion = emitir_sesion(db, usuario, contexto)
    auditoria.registrar(
        db, accion=auditoria.LOGIN, entidad=auditoria.ENTIDAD_USUARIO, entidad_id=usuario.id,
        actor=usuario, contexto=contexto,
    )
    db.commit()
    return sesion


# --- Refresh y logout ---------------------------------------------------------

def _sesion_por_token(db: Session, token: str | None, *, bloquear: bool) -> SesionRefresh | None:
    if not token:
        return None
    consulta = select(SesionRefresh).where(SesionRefresh.token_hash == hash_token(token))
    if bloquear:
        consulta = consulta.with_for_update()
    return db.scalars(consulta).first()


def refrescar(db: Session, token: str | None, contexto: ContextoPeticion) -> SesionEmitida:
    sesion = _sesion_por_token(db, token, bloquear=True)
    ahora = ahora_utc()
    if sesion is None or sesion.expira_at <= ahora:
        raise NoAutenticado()
    if sesion.revocado_at is not None:
        # Solo la gracia revoca una hoja dejando viva la familia: si esa hoja aparece, hay dos
        # poseedores de la familia (uno es un ladrón) y se revoca toda.
        if _familia_activa(db, sesion.familia):
            logger.warning(
                "Uso de un refresh token revocado con la familia activa: se revoca la familia "
                "(usuario %s)", sesion.usuario_id,
            )
            _revocar_familia(db, sesion.familia)
            db.commit()
        raise NoAutenticado()

    usuario = repo_usuarios.por_id(db, sesion.usuario_id)
    if usuario is None or not usuario.activo:
        _revocar_familia(db, sesion.familia)
        db.commit()
        raise NoAutenticado()

    if sesion.reemplazado_por is not None:
        en_gracia = sesion.reemplazado_at is not None and ahora - sesion.reemplazado_at <= GRACIA_REUSO
        if en_gracia and sesion.gracia_usada_at is None:
            # Se rotó hace instantes y la respuesta no llegó (o dos pestañas a la vez): un único
            # sucesor nuevo, y la hoja anterior queda revocada (una sola hoja activa por familia).
            _revocar_hojas(db, sesion.familia)
            sesion.gracia_usada_at = ahora
            emitida = emitir_sesion(db, usuario, contexto, sesion.familia)
            usuario.ultimo_acceso_at = ahora
            db.commit()
            return emitida
        logger.warning("Reuso de refresh token detectado: se revoca la familia (usuario %s)", usuario.id)
        _revocar_familia(db, sesion.familia)
        db.commit()
        raise NoAutenticado()

    nueva, refresh = _nueva_sesion_refresh(db, usuario, contexto, sesion.familia)
    sesion.reemplazado_por = nueva.id
    sesion.reemplazado_at = ahora
    usuario.ultimo_acceso_at = ahora
    access, vigencia = crear_access_token(usuario.id, usuario.token_version)
    db.commit()
    return SesionEmitida(usuario, access, vigencia, refresh)


def logout(db: Session, token: str | None, contexto: ContextoPeticion) -> None:
    sesion = _sesion_por_token(db, token, bloquear=True)
    if sesion is None:
        return
    _revocar_familia(db, sesion.familia)
    usuario = repo_usuarios.por_id(db, sesion.usuario_id)
    if usuario is not None and sesion.revocado_at is None:
        auditoria.registrar(
            db, accion=auditoria.LOGOUT, entidad=auditoria.ENTIDAD_USUARIO, entidad_id=usuario.id,
            actor=usuario, contexto=contexto,
        )
    db.commit()


# --- Recuperación y restablecimiento -----------------------------------------

def solicitar_recuperacion(db: Session, identificador: str, contexto: ContextoPeticion) -> None:
    """Siempre responde igual (el endpoint devuelve 202 exista o no el usuario)."""
    rate_limit.reservar(db, TipoIntento.recuperar, usuario=identificador, ip=contexto.ip, exito=True)
    usuario = repo_usuarios.por_identificador(db, identificador) if identificador.strip() else None
    if usuario is not None and usuario.activo and usuario.correo:
        # Solo el usuario: el token se genera al enviar (nunca queda en la cola).
        correo_service.encolar(
            db,
            tipo=correo_service.TIPO_RECUPERACION,
            asunto=ASUNTO_RECUPERACION,
            usuario_id=usuario.id,
            contexto={"ip": contexto.ip} if contexto.ip else {},
        )
        # La petición es anónima (cualquiera puede pedirla): sin actor; el usuario va en
        # entidad_id y el origen en la IP.
        auditoria.registrar(
            db, accion=auditoria.RECUPERAR_SOLICITADO, entidad=auditoria.ENTIDAD_USUARIO,
            entidad_id=usuario.id, contexto=contexto,
        )
    db.commit()


def restablecer(db: Session, token: str, password: str, contexto: ContextoPeticion) -> None:
    intento = rate_limit.reservar(db, TipoIntento.restablecer, usuario=None, ip=contexto.ip)
    ahora = ahora_utc()
    reset = db.scalars(
        select(PasswordReset).where(PasswordReset.token_hash == hash_token(token)).with_for_update()
    ).first() if token else None
    usuario = repo_usuarios.por_id(db, reset.usuario_id) if reset else None
    if (
        reset is None or reset.usado_at is not None or reset.expira_at <= ahora
        or usuario is None or not usuario.activo
    ):
        db.commit()
        raise SolicitudInvalida(MENSAJE_ENLACE_INVALIDO)

    # La política se valida antes de consumir el enlace, para poder corregir y reintentar.
    try:
        validar_politica(password, usuario.username)
    except DatosInvalidos:
        db.commit()
        raise

    reset.usado_at = ahora
    usuario.password_hash = hash_password(password)
    usuario.password_cambiada_at = ahora
    usuario.debe_cambiar_password = False
    invalidar_accesos(db, usuario)  # también consume los demás enlaces pendientes
    rate_limit.marcar_exito(db, intento)
    auditoria.registrar(
        db, accion=auditoria.PASSWORD_RESTABLECIDO, entidad=auditoria.ENTIDAD_USUARIO,
        entidad_id=usuario.id, actor=usuario, contexto=contexto,
    )
    db.commit()


# --- Cambio de contraseña -----------------------------------------------------

def _clave_cambio(usuario: Usuario) -> str:
    """Clave del límite de cambio de contraseña: por usuario (id), no por nombre."""
    return f"usuario:{usuario.id}"


def cambiar_password(
    db: Session, usuario: Usuario, password_actual: str, password_nueva: str,
    contexto: ContextoPeticion,
) -> SesionEmitida:
    clave = _clave_cambio(usuario)
    intento = rate_limit.reservar(db, TipoIntento.cambiar_password, usuario=clave, ip=contexto.ip)
    if not verificar_password(password_actual, usuario.password_hash):
        auditoria.registrar(
            db, accion=auditoria.PASSWORD_CAMBIO_FALLIDO, entidad=auditoria.ENTIDAD_USUARIO,
            entidad_id=usuario.id, actor=usuario, detalle={"motivo": "password_actual_incorrecta"},
            contexto=contexto,
        )
        if rate_limit.limite_alcanzado(
            db, TipoIntento.cambiar_password, usuario=clave, ip=contexto.ip
        ):
            # Al llegar al límite puede tratarse de un access token robado: se cierran todos los
            # accesos (el dueño vuelve a ingresar con su contraseña, que sigue igual).
            invalidar_accesos(db, usuario)
        db.commit()
        raise SolicitudInvalida("La contraseña actual no es correcta.")
    rate_limit.marcar_exito(db, intento)
    db.commit()
    if password_actual == password_nueva:
        raise DatosInvalidos("La nueva contraseña debe ser distinta de la actual.")
    validar_politica(password_nueva, usuario.username)

    usuario.password_hash = hash_password(password_nueva)
    usuario.password_cambiada_at = ahora_utc()
    usuario.debe_cambiar_password = False
    invalidar_accesos(db, usuario)
    sesion = emitir_sesion(db, usuario, contexto)
    auditoria.registrar(
        db, accion=auditoria.PASSWORD_CAMBIADO, entidad=auditoria.ENTIDAD_USUARIO,
        entidad_id=usuario.id, actor=usuario, contexto=contexto,
    )
    db.commit()
    return sesion


# --- Mantenimiento ------------------------------------------------------------

def limpiar_vencidos(db: Session) -> tuple[int, int]:
    """Borra sesiones y enlaces de recuperación vencidos, revocados o usados hace más de 30 días.

    Devuelve ``(sesiones, enlaces)`` borrados (el commit lo hace quien llama).
    """
    limite = ahora_utc() - RETENCION_LIMPIEZA
    sesiones = db.execute(
        delete(SesionRefresh).where(
            or_(SesionRefresh.expira_at < limite, SesionRefresh.revocado_at < limite)
        )
    ).rowcount or 0
    enlaces = db.execute(
        delete(PasswordReset).where(
            or_(PasswordReset.expira_at < limite, PasswordReset.usado_at < limite)
        )
    ).rowcount or 0
    return sesiones, enlaces
