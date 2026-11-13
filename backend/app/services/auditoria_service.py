"""Auditoría: registro de solo inserción con detalle antes/después en lista blanca.

El detalle nunca lleva hashes, contraseñas ni tokens: las instantáneas de una entidad solo copian
los campos de su lista blanca y, como segunda barrera, :func:`limpiar_detalle` descarta cualquier
clave con nombre sensible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any

from sqlalchemy.orm import Session

from app.core.errores import DatosInvalidos
from app.core.tiempo import ahora_utc, inicio_dia_lima, zona_lima
from app.models import Auditoria, Usuario
from app.repositories import auditoria as repo_auditoria
from app.services.contexto import ContextoPeticion

# Acciones (§5). Las de fases siguientes se agregan aquí.
LOGIN = "login"
LOGIN_FALLIDO = "login_fallido"
LOGOUT = "logout"
RECUPERAR_SOLICITADO = "recuperar_solicitado"
PASSWORD_RESTABLECIDO = "password_restablecido"
PASSWORD_CAMBIADO = "password_cambiado"
PASSWORD_CAMBIO_FALLIDO = "password_cambio_fallido"
USUARIO_CREADO = "usuario_creado"
USUARIO_EDITADO = "usuario_editado"
ROL_CAMBIADO = "rol_cambiado"
USUARIO_DESACTIVADO = "usuario_desactivado"
USUARIO_ACTIVADO = "usuario_activado"
PASSWORD_TEMPORAL_ASIGNADO = "password_temporal_asignado"

ACCIONES = (
    LOGIN, LOGIN_FALLIDO, LOGOUT, RECUPERAR_SOLICITADO, PASSWORD_RESTABLECIDO, PASSWORD_CAMBIADO,
    PASSWORD_CAMBIO_FALLIDO,
    USUARIO_CREADO, USUARIO_EDITADO, ROL_CAMBIADO, USUARIO_DESACTIVADO, USUARIO_ACTIVADO,
    PASSWORD_TEMPORAL_ASIGNADO,
)

ENTIDAD_USUARIO = "usuario"
ENTIDADES = (ENTIDAD_USUARIO,)

# Riego aplicado: carga de Excel (F2, §3.5). Entidad ``carga_riego`` con el id de la carga.
EXCEL_SUBIDO = "excel_subido"
EXCEL_CONFIRMADO = "excel_confirmado"
EXCEL_DESCARTADO = "excel_descartado"
ENTIDAD_CARGA_RIEGO = "carga_riego"
ACCIONES += (EXCEL_SUBIDO, EXCEL_CONFIRMADO, EXCEL_DESCARTADO)
ENTIDADES += (ENTIDAD_CARGA_RIEGO,)

# Datos de campo: WeatherLink reemplaza lecturas del Excel histórico (reprocesar-weatherlink
# --pisar-excel). Entidad ``ingesta_corrida`` con el id de la corrida de reproceso.
METEO_EXCEL_PISADO = "meteo_excel_pisado"
ENTIDAD_INGESTA_CORRIDA = "ingesta_corrida"
ACCIONES += (METEO_EXCEL_PISADO,)
ENTIDADES += (ENTIDAD_INGESTA_CORRIDA,)

# Riego por pulsos: edición de los parámetros del módulo. Entidad ``modulo`` con el id del módulo.
PARAMETROS_PULSOS_ACTUALIZADOS = "actualizar_parametros_pulsos"
ENTIDAD_MODULO = "modulo"
ACCIONES += (PARAMETROS_PULSOS_ACTUALIZADOS,)
ENTIDADES += (ENTIDAD_MODULO,)

ACTOR_SISTEMA = "sistema"

# Lista blanca de campos por entidad para las instantáneas antes/después.
CAMPOS_USUARIO = ("username", "nombre", "correo", "rol", "activo", "debe_cambiar_password")

_CLAVE_SENSIBLE = re.compile(r"(?i)(password|contrase|hash|token|secret|api[_-]?key|cookie)")
_LARGO_TEXTO = 500


def _valor_json(valor: Any) -> Any:
    if isinstance(valor, Enum):
        return valor.value
    if isinstance(valor, datetime | date):
        return valor.isoformat()
    if isinstance(valor, str):
        return valor[:_LARGO_TEXTO]
    return valor


def limpiar_detalle(detalle: Any) -> Any:
    """Copia el detalle quitando claves sensibles a cualquier profundidad."""
    if isinstance(detalle, dict):
        return {
            str(k): limpiar_detalle(v)
            for k, v in detalle.items()
            if not _CLAVE_SENSIBLE.search(str(k))
        }
    if isinstance(detalle, list | tuple):
        return [limpiar_detalle(v) for v in detalle]
    return _valor_json(detalle)


def instantanea_usuario(usuario: Usuario) -> dict[str, Any]:
    return {campo: _valor_json(getattr(usuario, campo)) for campo in CAMPOS_USUARIO}


def diferencias(antes: dict[str, Any], despues: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``{"antes": {...}, "despues": {...}}`` solo con los campos que cambiaron."""
    campos = [c for c in despues if antes.get(c) != despues.get(c)]
    return {
        "antes": {c: antes.get(c) for c in campos},
        "despues": {c: despues.get(c) for c in campos},
    }


def registrar(
    db: Session,
    *,
    accion: str,
    entidad: str,
    entidad_id: int | str | None = None,
    actor: Usuario | None = None,
    actor_username: str | None = None,
    detalle: dict[str, Any] | None = None,
    contexto: ContextoPeticion | None = None,
) -> Auditoria:
    """Agrega una fila de auditoría a la sesión (el commit lo hace quien llama).

    ``actor`` es el usuario que hace la acción; sin actor se usa ``actor_username``
    (p. ej. "sistema" para la CLI). Nunca pasar texto escrito por un anónimo (un login fallido
    de un usuario inexistente se audita sin usuario).
    """
    contexto = contexto or ContextoPeticion()
    fila = Auditoria(
        # Reloj de la app (no now() de la BD): el mismo que usan límites y vencimientos.
        ocurrido_at=ahora_utc(),
        usuario_id=actor.id if actor else None,
        username=(actor.username if actor else actor_username or None),
        rol=(_valor_json(actor.rol) if actor else None),
        accion=accion,
        entidad=entidad,
        entidad_id=None if entidad_id is None else str(entidad_id)[:60],
        detalle=limpiar_detalle(detalle) if detalle else None,
        ip=contexto.ip,
        user_agent=contexto.user_agent,
    )
    if fila.username:
        fila.username = fila.username[:60]
    db.add(fila)
    return fila


# --- Consulta -----------------------------------------------------------------

@dataclass(frozen=True)
class FiltroAuditoria:
    usuario_id: int | None = None
    accion: str | None = None
    entidad: str | None = None
    entidad_id: str | None = None
    desde: str | None = None
    hasta: str | None = None


def _parsear_limite(valor: str, campo: str, *, es_hasta: bool) -> datetime:
    """Fecha ``YYYY-MM-DD`` (día completo en Lima) o fecha y hora ISO 8601 (sin zona = Lima)."""
    texto = valor.strip()
    try:
        if len(texto) == 10:
            dia = date.fromisoformat(texto)
            return inicio_dia_lima(dia + timedelta(days=1) if es_hasta else dia)
        instante = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        raise DatosInvalidos(f"El parámetro {campo} no es una fecha válida (use AAAA-MM-DD).") from None
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=zona_lima())
    return instante


def _condiciones(filtro: FiltroAuditoria) -> list:
    condiciones = []
    if filtro.usuario_id is not None:
        condiciones.append(Auditoria.usuario_id == filtro.usuario_id)
    if filtro.accion:
        condiciones.append(Auditoria.accion == filtro.accion)
    if filtro.entidad:
        condiciones.append(Auditoria.entidad == filtro.entidad)
    if filtro.entidad_id:
        condiciones.append(Auditoria.entidad_id == filtro.entidad_id)
    desde = _parsear_limite(filtro.desde, "desde", es_hasta=False) if filtro.desde else None
    hasta = _parsear_limite(filtro.hasta, "hasta", es_hasta=True) if filtro.hasta else None
    if desde and hasta and desde >= hasta:
        raise DatosInvalidos("La fecha desde debe ser anterior a la fecha hasta.")
    if desde:
        condiciones.append(Auditoria.ocurrido_at >= desde)
    if hasta:
        # Con fecha sola, "hasta" incluye todo ese día (límite exclusivo al día siguiente).
        if filtro.hasta and len(filtro.hasta.strip()) == 10:
            condiciones.append(Auditoria.ocurrido_at < hasta)
        else:
            condiciones.append(Auditoria.ocurrido_at <= hasta)
    return condiciones


def listar(
    db: Session, filtro: FiltroAuditoria, *, page: int = 1, page_size: int = 50
) -> tuple[list[Auditoria], int]:
    return repo_auditoria.pagina(db, _condiciones(filtro), page=page, page_size=page_size)


def opciones(db: Session) -> dict[str, Any]:
    acciones = set(ACCIONES) | repo_auditoria.acciones_distintas(db)
    entidades = set(ENTIDADES) | repo_auditoria.entidades_distintas(db)
    return {
        "acciones": sorted(acciones),
        "entidades": sorted(entidades),
        "usuarios": repo_auditoria.usuarios_para_filtro(db),
    }

