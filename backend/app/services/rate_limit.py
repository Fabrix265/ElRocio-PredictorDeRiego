"""Límite de intentos contado en la BD (tabla ``intento_login``), según §7.

- login: 5 fallos / 15 min por usuario+IP, 30 / 15 min por IP y 10 / 15 min por usuario.
  Un ingreso correcto del usuario reinicia sus contadores por usuario.
- recuperar: 3 / h por usuario (o correo) y 10 / h por IP (cuentan todas las solicitudes).
- restablecer: 10 / 15 min por IP (cuentan todos los intentos).

Se cuenta en la BD (no en memoria) para que valga con varios procesos y tras reinicios. Las horas
salen del reloj de la app (``ahora_utc``), igual que el resto de reglas de vencimiento.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.errores import LimiteExcedido
from app.core.tiempo import ahora_utc
from app.models import IntentoLogin
from app.models.enums import TipoIntento


@dataclass(frozen=True)
class Regla:
    maximo: int
    ventana: timedelta
    por_usuario: bool
    por_ip: bool
    solo_fallos: bool


LOGIN_USUARIO_IP = Regla(5, timedelta(minutes=15), por_usuario=True, por_ip=True, solo_fallos=True)
LOGIN_IP = Regla(30, timedelta(minutes=15), por_usuario=False, por_ip=True, solo_fallos=True)
LOGIN_USUARIO = Regla(10, timedelta(minutes=15), por_usuario=True, por_ip=False, solo_fallos=True)
RECUPERAR_USUARIO = Regla(3, timedelta(hours=1), por_usuario=True, por_ip=False, solo_fallos=False)
RECUPERAR_IP = Regla(10, timedelta(hours=1), por_usuario=False, por_ip=True, solo_fallos=False)
RESTABLECER_IP = Regla(10, timedelta(minutes=15), por_usuario=False, por_ip=True, solo_fallos=False)

REGLAS: dict[TipoIntento, tuple[Regla, ...]] = {
    TipoIntento.login: (LOGIN_USUARIO_IP, LOGIN_IP, LOGIN_USUARIO),
    TipoIntento.recuperar: (RECUPERAR_USUARIO, RECUPERAR_IP),
    TipoIntento.restablecer: (RESTABLECER_IP,),
}

LARGO_USUARIO = 254


def normalizar_usuario(valor: str | None) -> str | None:
    if valor is None:
        return None
    return valor.strip().lower()[:LARGO_USUARIO] or None


def _ultimo_exito(db: Session, tipo: TipoIntento, usuario: str) -> datetime | None:
    return db.scalar(
        select(func.max(IntentoLogin.created_at)).where(
            IntentoLogin.tipo == tipo,
            IntentoLogin.username_intentado == usuario,
            IntentoLogin.exito.is_(True),
        )
    )


def _bloqueado_hasta(
    db: Session, tipo: TipoIntento, regla: Regla, usuario: str | None, ip: str | None,
    ahora: datetime,
) -> datetime | None:
    if (regla.por_usuario and not usuario) or (regla.por_ip and not ip):
        return None
    desde = ahora - regla.ventana
    condiciones = [IntentoLogin.tipo == tipo, IntentoLogin.created_at > desde]
    if regla.por_usuario:
        condiciones.append(IntentoLogin.username_intentado == usuario)
        if regla.solo_fallos:
            exito = _ultimo_exito(db, tipo, usuario)
            if exito is not None:
                condiciones.append(IntentoLogin.created_at > exito)
    if regla.por_ip:
        condiciones.append(IntentoLogin.ip == ip)
    if regla.solo_fallos:
        condiciones.append(IntentoLogin.exito.is_(False))
    # El intento n.º `maximo` más reciente dentro de la ventana: si existe, se llegó al límite
    # y el bloqueo dura hasta que salga de la ventana.
    enesimo = db.scalar(
        select(IntentoLogin.created_at)
        .where(*condiciones)
        .order_by(IntentoLogin.created_at.desc())
        .offset(regla.maximo - 1)
        .limit(1)
    )
    return None if enesimo is None else enesimo + regla.ventana


def verificar(db: Session, tipo: TipoIntento, *, usuario: str | None, ip: str | None) -> None:
    """Lanza :class:`LimiteExcedido` si alguna regla del tipo está en su máximo."""
    ahora = ahora_utc()
    usuario = normalizar_usuario(usuario)
    hasta = [
        h for regla in REGLAS[tipo]
        if (h := _bloqueado_hasta(db, tipo, regla, usuario, ip, ahora)) is not None and h > ahora
    ]
    if hasta:
        raise LimiteExcedido((max(hasta) - ahora).total_seconds())


def registrar(
    db: Session, tipo: TipoIntento, *, usuario: str | None, ip: str | None, exito: bool
) -> None:
    db.add(
        IntentoLogin(
            tipo=tipo,
            username_intentado=normalizar_usuario(usuario),
            ip=ip,
            exito=exito,
            created_at=ahora_utc(),
        )
    )


def limpiar_antiguos(db: Session, *, dias: int = 30) -> int:
    """Borra intentos con más de ``dias`` (mantenimiento diario)."""
    resultado = db.execute(
        delete(IntentoLogin).where(IntentoLogin.created_at < ahora_utc() - timedelta(days=dias))
    )
    return resultado.rowcount or 0
