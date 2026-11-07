"""Cola de correos (outbox ``notificacion_correo``) y su procesamiento.

- :func:`encolar` agrega una fila ``pendiente`` en la misma transacción que la acción que la origina.
  ``contexto`` nunca lleva secretos: el correo de recuperación guarda solo ``usuario_id`` y el token
  se genera al enviar.
- :func:`reclamar` toma un lote con ``SELECT … FOR UPDATE SKIP LOCKED`` y lo pasa a ``enviando``
  con ``bloqueado_hasta`` (si el proceso muere, otro lo retoma al vencer ese plazo).
- :func:`procesar_pendientes` resuelve destinatarios, arma el mensaje y lo envía. Si falla,
  reintenta con espera creciente; al quinto intento queda en ``error``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import redactar
from app.core.security import generar_token_opaco, hash_token
from app.core.tiempo import ahora_utc
from app.emails import renderizar
from app.emails.smtp import Mailer, remitente
from app.models import NotificacionCorreo, PasswordReset, Usuario
from app.models.enums import EstadoCorreo, RolUsuario
from app.repositories import usuarios as repo_usuarios

logger = logging.getLogger(__name__)

TIPO_RECUPERACION = "recuperacion"
MAX_INTENTOS = 5
# Espera antes del intento n.º 2, 3, 4 y 5.
ESPERAS_REINTENTO = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1))
BLOQUEO_ENVIO = timedelta(minutes=5)
LOTE_POR_DEFECTO = 20


def encolar(
    db: Session,
    *,
    tipo: str,
    asunto: str,
    usuario_id: int | None = None,
    rol_destino: RolUsuario | None = None,
    cronograma_id: int | None = None,
    contexto: dict[str, Any] | None = None,
) -> NotificacionCorreo:
    notificacion = NotificacionCorreo(
        tipo=tipo,
        asunto=asunto,
        usuario_id=usuario_id,
        rol_destino=rol_destino,
        cronograma_id=cronograma_id,
        contexto=contexto or {},
        estado=EstadoCorreo.pendiente,
        intentos=0,
        proximo_intento_at=ahora_utc(),
    )
    db.add(notificacion)
    return notificacion


def reclamar(db: Session, limite: int = LOTE_POR_DEFECTO) -> list[int]:
    """Marca como ``enviando`` un lote listo para enviar y devuelve sus IDs (hace commit)."""
    ahora = ahora_utc()
    candidatos = (
        select(NotificacionCorreo.id)
        .where(
            or_(
                (NotificacionCorreo.estado == EstadoCorreo.pendiente)
                & (NotificacionCorreo.proximo_intento_at <= ahora),
                (NotificacionCorreo.estado == EstadoCorreo.enviando)
                & (NotificacionCorreo.bloqueado_hasta < ahora),
            )
        )
        .order_by(NotificacionCorreo.proximo_intento_at, NotificacionCorreo.id)
        .limit(limite)
        .with_for_update(skip_locked=True)
    )
    ids = list(
        db.scalars(
            update(NotificacionCorreo)
            .where(NotificacionCorreo.id.in_(candidatos.scalar_subquery()))
            .values(estado=EstadoCorreo.enviando, bloqueado_hasta=ahora + BLOQUEO_ENVIO)
            .returning(NotificacionCorreo.id)
            .execution_options(synchronize_session=False)
        )
    )
    db.commit()
    return sorted(ids)


# --- Preparación de cada tipo -------------------------------------------------

@dataclass
class CorreoPreparado:
    destinatarios: list[str]
    asunto: str
    plantilla: str
    contexto: dict[str, Any] = field(default_factory=dict)


Preparador = Callable[[Session, NotificacionCorreo], CorreoPreparado | None]


def _preparar_recuperacion(db: Session, notificacion: NotificacionCorreo) -> CorreoPreparado | None:
    usuario = db.get(Usuario, notificacion.usuario_id) if notificacion.usuario_id else None
    if usuario is None or not usuario.activo or not usuario.correo:
        return None
    ahora = ahora_utc()
    # Al crear un enlace nuevo se invalidan los anteriores sin usar.
    db.execute(
        update(PasswordReset)
        .where(PasswordReset.usuario_id == usuario.id, PasswordReset.usado_at.is_(None))
        .values(usado_at=ahora)
        .execution_options(synchronize_session=False)
    )
    token = generar_token_opaco()
    minutos = settings.password_reset_minutes
    db.add(
        PasswordReset(
            usuario_id=usuario.id,
            token_hash=hash_token(token),
            expira_at=ahora + timedelta(minutes=minutos),
            ip=(notificacion.contexto or {}).get("ip"),
        )
    )
    db.flush()
    # El token va en el fragmento (#): no llega a los logs del servidor web ni al Referer.
    enlace = f"{settings.frontend_url.rstrip('/')}/restablecer#token={token}"
    return CorreoPreparado(
        destinatarios=[usuario.correo],
        asunto=notificacion.asunto,
        plantilla="recuperacion",
        contexto={
            "nombre": usuario.nombre,
            "username": usuario.username,
            "enlace": enlace,
            "minutos": minutos,
        },
    )


def _preparar_por_rol(db: Session, notificacion: NotificacionCorreo) -> CorreoPreparado | None:
    """Correos de flujo (F4): destinatarios = usuarios activos con el rol al momento de enviar."""
    if notificacion.rol_destino is None:
        destinatarios = list(notificacion.destinatarios or [])
    else:
        destinatarios = repo_usuarios.destinatarios_por_rol(db, notificacion.rol_destino)
    if not destinatarios:
        return None
    return CorreoPreparado(
        destinatarios=destinatarios,
        asunto=notificacion.asunto,
        plantilla=notificacion.tipo,
        contexto=dict(notificacion.contexto or {}),
    )


PREPARADORES: dict[str, Preparador] = {TIPO_RECUPERACION: _preparar_recuperacion}


def construir_mensaje(preparado: CorreoPreparado, tipo: str) -> EmailMessage:
    html, texto = renderizar(preparado.plantilla, {"asunto": preparado.asunto, **preparado.contexto})
    mensaje = EmailMessage()
    mensaje["Subject"] = preparado.asunto
    mensaje["From"] = remitente()
    if len(preparado.destinatarios) == 1:
        mensaje["To"] = preparado.destinatarios[0]
    else:
        # Varios destinatarios: en copia oculta para no exponer los correos entre sí.
        mensaje["To"] = remitente()
        mensaje["Bcc"] = ", ".join(preparado.destinatarios)
    mensaje["Date"] = formatdate(localtime=False)
    mensaje["Message-ID"] = make_msgid(domain="riego.local")
    mensaje["X-Riego-Tipo"] = tipo
    mensaje.set_content(texto or "Este correo requiere un cliente compatible con HTML.")
    mensaje.add_alternative(html, subtype="html")
    return mensaje


# --- Procesamiento ------------------------------------------------------------

@dataclass
class ResultadoEnvio:
    enviados: int = 0
    sin_destinatarios: int = 0
    reintentos: int = 0
    errores: int = 0

    @property
    def total(self) -> int:
        return self.enviados + self.sin_destinatarios + self.reintentos + self.errores


def _registrar_fallo(db: Session, notificacion_id: int, error: Exception) -> str:
    notificacion = db.get(NotificacionCorreo, notificacion_id, populate_existing=True)
    notificacion.intentos = (notificacion.intentos or 0) + 1
    notificacion.ultimo_error = redactar(f"{type(error).__name__}: {error}")[:500]
    notificacion.bloqueado_hasta = None
    if notificacion.intentos >= MAX_INTENTOS:
        notificacion.estado = EstadoCorreo.error
        resultado = "error"
    else:
        espera = ESPERAS_REINTENTO[min(notificacion.intentos, len(ESPERAS_REINTENTO)) - 1]
        notificacion.estado = EstadoCorreo.pendiente
        notificacion.proximo_intento_at = ahora_utc() + espera
        resultado = "reintento"
    db.commit()
    return resultado


def procesar_uno(db: Session, notificacion_id: int, mailer: Mailer) -> str:
    """Envía una notificación reclamada. Devuelve enviado / sin_destinatarios / reintento / error."""
    try:
        with db.begin_nested():  # el token de recuperación solo queda si el envío funcionó
            notificacion = db.get(NotificacionCorreo, notificacion_id, populate_existing=True)
            if notificacion is None or notificacion.estado != EstadoCorreo.enviando:
                resultado = "omitido"  # lo tomó otro proceso o ya no está en envío
            else:
                resultado = _enviar(db, notificacion, mailer)
        db.commit()
        return resultado
    except Exception as error:  # noqa: BLE001 - cualquier fallo de envío se reintenta
        logger.warning("No se pudo enviar el correo %s: %s", notificacion_id, type(error).__name__)
        return _registrar_fallo(db, notificacion_id, error)


def _enviar(db: Session, notificacion: NotificacionCorreo, mailer: Mailer) -> str:
    preparado = PREPARADORES.get(notificacion.tipo, _preparar_por_rol)(db, notificacion)
    notificacion.bloqueado_hasta = None
    if preparado is None:
        notificacion.estado = EstadoCorreo.sin_destinatarios
        return "sin_destinatarios"
    mailer.enviar(construir_mensaje(preparado, notificacion.tipo))
    notificacion.estado = EstadoCorreo.enviado
    notificacion.enviado_at = ahora_utc()
    notificacion.ultimo_error = None
    notificacion.destinatarios = preparado.destinatarios
    notificacion.intentos = (notificacion.intentos or 0) + 1
    return "enviado"


def procesar_pendientes(db: Session, mailer: Mailer, *, limite: int = LOTE_POR_DEFECTO) -> ResultadoEnvio:
    resultado = ResultadoEnvio()
    for notificacion_id in reclamar(db, limite):
        estado = procesar_uno(db, notificacion_id, mailer)
        if estado == "enviado":
            resultado.enviados += 1
        elif estado == "sin_destinatarios":
            resultado.sin_destinatarios += 1
        elif estado == "reintento":
            resultado.reintentos += 1
        elif estado == "error":
            resultado.errores += 1
    return resultado
