"""Límite de intentos contado en la BD (tabla ``intento_login``), según §7.

- login: 5 fallos / 15 min por usuario+IP, 30 / 15 min por IP y 10 / 15 min por usuario.
  Un ingreso correcto del usuario reinicia sus contadores por usuario.
- recuperar: 3 / h por usuario (o correo) y 10 / h por IP (cuentan todas las solicitudes).
- restablecer: 10 / 15 min por IP (cuentan todos los intentos).
- cambiar_password: 5 fallos / 15 min por usuario (contraseña actual incorrecta).

Sin carreras entre verificar y registrar: :func:`reservar` inserta el intento (como fallo) y hace
commit **antes** de contar, así las peticiones simultáneas se ven entre sí. Si al contar (sin el
propio intento) alguna regla ya está en su máximo, el intento se borra y se rechaza con 429; si
varias reservan a la vez, todas pueden quedar rechazadas (el error queda del lado seguro). Si la
operación sale bien, :func:`marcar_exito` cambia el intento a ``exito=true``.

El usuario intentado se guarda como HMAC-SHA256 del valor normalizado (nunca el texto: alguien
puede escribir su contraseña en el campo usuario); el conteo funciona igual.

Se cuenta en la BD (no en memoria) para que valga con varios procesos y tras reinicios. Las horas
salen del reloj de la app (``ahora_utc``), igual que el resto de reglas de vencimiento.

Transacciones: :func:`reservar` es la **excepción documentada** a la convención del backend (los
servicios hacen ``flush`` y confirma quien llama): hace commit para que el intento sea visible a
las demás peticiones antes de contar, y lo vuelve a hacer al borrar un intento rechazado.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import LimiteExcedido
from app.core.tiempo import ahora_utc
from app.models import IntentoLogin
from app.models.enums import TipoIntento
from app.repositories import intentos as repo_intentos


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
CAMBIAR_PASSWORD_USUARIO = Regla(
    5, timedelta(minutes=15), por_usuario=True, por_ip=False, solo_fallos=True
)

REGLAS: dict[TipoIntento, tuple[Regla, ...]] = {
    TipoIntento.login: (LOGIN_USUARIO_IP, LOGIN_IP, LOGIN_USUARIO),
    TipoIntento.recuperar: (RECUPERAR_USUARIO, RECUPERAR_IP),
    TipoIntento.restablecer: (RESTABLECER_IP,),
    TipoIntento.cambiar_password: (CAMBIAR_PASSWORD_USUARIO,),
}

LARGO_USUARIO = 254
_CONTEXTO_HMAC = b"riego:intento_login:usuario:"


def normalizar_usuario(valor: str | None) -> str | None:
    if valor is None:
        return None
    return valor.strip().lower()[:LARGO_USUARIO] or None


def clave_usuario(valor: str | None) -> str | None:
    """HMAC-SHA256 (hex) del usuario normalizado: lo que se guarda y se compara en la BD."""
    normalizado = normalizar_usuario(valor)
    if normalizado is None:
        return None
    llave = _CONTEXTO_HMAC + settings.jwt_secret.get_secret_value().encode("utf-8")
    return hmac.new(llave, normalizado.encode("utf-8"), hashlib.sha256).hexdigest()


def _bloqueado_hasta(
    db: Session, tipo: TipoIntento, regla: Regla, usuario: str | None, ip: str | None,
    ahora: datetime, excluir_id: int | None = None,
) -> datetime | None:
    if (regla.por_usuario and not usuario) or (regla.por_ip and not ip):
        return None
    desde = ahora - regla.ventana
    condiciones = [IntentoLogin.tipo == tipo, IntentoLogin.created_at > desde]
    if excluir_id is not None:
        condiciones.append(IntentoLogin.id != excluir_id)
    if regla.por_usuario:
        condiciones.append(IntentoLogin.username_intentado == usuario)
        if regla.solo_fallos:
            exito = repo_intentos.ultimo_exito(db, tipo, usuario)
            if exito is not None:
                condiciones.append(IntentoLogin.created_at > exito)
    if regla.por_ip:
        condiciones.append(IntentoLogin.ip == ip)
    if regla.solo_fallos:
        condiciones.append(IntentoLogin.exito.is_(False))
    # El intento n.º `maximo` más reciente dentro de la ventana: si existe, se llegó al límite
    # y el bloqueo dura hasta que salga de la ventana.
    enesimo = repo_intentos.enesimo_reciente(db, condiciones, regla.maximo)
    return None if enesimo is None else enesimo + regla.ventana


def _segundos_bloqueo(
    db: Session, tipo: TipoIntento, usuario: str | None, ip: str | None,
    excluir_id: int | None = None,
) -> float | None:
    ahora = ahora_utc()
    hasta = [
        h for regla in REGLAS[tipo]
        if (h := _bloqueado_hasta(db, tipo, regla, usuario, ip, ahora, excluir_id)) is not None
        and h > ahora
    ]
    return (max(hasta) - ahora).total_seconds() if hasta else None


def limite_alcanzado(db: Session, tipo: TipoIntento, *, usuario: str | None, ip: str | None) -> bool:
    """Solo consulta: ``True`` si alguna regla del tipo está en su máximo."""
    return _segundos_bloqueo(db, tipo, clave_usuario(usuario), ip) is not None


def verificar(db: Session, tipo: TipoIntento, *, usuario: str | None, ip: str | None) -> None:
    """Solo consulta: lanza :class:`LimiteExcedido` si alguna regla está en su máximo.

    No protege de peticiones simultáneas; para limitar una operación usar :func:`reservar`.
    """
    segundos = _segundos_bloqueo(db, tipo, clave_usuario(usuario), ip)
    if segundos is not None:
        raise LimiteExcedido(segundos)


def reservar(
    db: Session, tipo: TipoIntento, *, usuario: str | None, ip: str | None, exito: bool = False
) -> IntentoLogin:
    """Registra el intento (``exito=False`` salvo que se indique) con commit y luego cuenta.

    Lanza :class:`LimiteExcedido` (y borra el intento) si, sin contarlo, alguna regla ya está en
    su máximo. Hace commit de la sesión: llamar al inicio de la operación.
    """
    intento = IntentoLogin(
        tipo=tipo, username_intentado=clave_usuario(usuario), ip=ip, exito=exito,
        created_at=ahora_utc(),
    )
    db.add(intento)
    db.commit()  # visible para las demás peticiones antes de contar
    segundos = _segundos_bloqueo(db, tipo, intento.username_intentado, ip, excluir_id=intento.id)
    if segundos is not None:
        repo_intentos.borrar(db, intento.id)
        db.commit()
        raise LimiteExcedido(segundos)
    return intento


def marcar_exito(db: Session, intento: IntentoLogin) -> None:
    """El intento reservado salió bien (el commit lo hace quien llama)."""
    repo_intentos.marcar_exito(db, intento.id)


def limpiar_antiguos(db: Session, *, dias: int = 30) -> int:
    """Borra intentos con más de ``dias`` (mantenimiento diario)."""
    return repo_intentos.borrar_anteriores(db, ahora_utc() - timedelta(days=dias))
