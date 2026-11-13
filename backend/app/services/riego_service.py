"""Riego aplicado: consulta por módulo y rango, e historial de versiones de un turno-día (§4).

Incluye edición manual y sincronización provisional (F4); la carga de Excel está en
:mod:`app.services.carga_riego_service`.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

from sqlalchemy.orm import Session

from app.core.errores import Conflicto, DatosInvalidos, NoEncontrado, SinPermiso
from app.core.tiempo import ahora_lima, ahora_utc, fuera_de_limites, hoy_lima, mensaje_fuera_de_limites
from app.models import Cronograma, CronogramaEvento, CronogramaVersion, Modulo, RiegoRegistro, Turno, Usuario
from app.models.enums import EstadoRiego, OrigenRiego, RolUsuario, TipoEventoCronograma
from app.repositories import cronogramas as repo_cronogramas
from app.repositories import riego as repo
from app.schemas.riego import RegistroRiegoEntrada
from app.services import auditoria_service, calculo_pulsos
from app.services.contexto import ContextoPeticion
from app.services.riego_contenido import hash_contenido

DIAS_POR_DEFECTO = 14
MAX_DIAS_RANGO = 366


def rango(desde: dt.date | None, hasta: dt.date | None) -> tuple[dt.date, dt.date]:
    """Rango inclusivo; por defecto los últimos 14 días hasta hoy (Lima)."""
    if fuera_de_limites(desde, hasta) is not None:
        raise DatosInvalidos(mensaje_fuera_de_limites())
    hasta = hasta or hoy_lima()
    desde = desde or hasta - dt.timedelta(days=DIAS_POR_DEFECTO - 1)
    if desde > hasta:
        raise DatosInvalidos("La fecha desde debe ser igual o anterior a la fecha hasta.")
    if (hasta - desde).days + 1 > MAX_DIAS_RANGO:
        raise DatosInvalidos(f"El rango máximo es de {MAX_DIAS_RANGO} días.")
    return desde, hasta


def _registro(registro: RiegoRegistro, turnos: dict[int, str], nombres: dict[int, str],
              *, con_version: bool = False) -> dict[str, Any]:
    salida = {
        "id": registro.id, "turno_id": registro.turno_id, "turno_codigo": turnos.get(registro.turno_id),
        "fecha": registro.fecha, "version": registro.version, "estado": registro.estado,
        "origen": registro.origen, "sin_riego": registro.sin_riego, "motivo": registro.motivo,
        "comentario": registro.comentario, "carga_id": registro.carga_id,
        "creado_at": registro.created_at.astimezone(dt.UTC) if registro.created_at else None,
        "creado_por": nombres.get(registro.creado_por),
        "ciclos": list(registro.ciclos),
    }
    if con_version:
        salida |= {"vigente": registro.vigente, "basado_en_id": registro.basado_en_id}
    return salida


def listar(db: Session, modulo_id: int, desde: dt.date | None, hasta: dt.date | None) -> dict[str, Any]:
    """Registros vigentes del módulo (día × turno × ciclos con estado) en ``[desde, hasta]``."""
    modulo = db.get(Modulo, modulo_id)
    if modulo is None:
        raise NoEncontrado("No existe el módulo indicado.")
    desde, hasta = rango(desde, hasta)
    registros = repo.vigentes(db, modulo.id, desde=desde, hasta=hasta + dt.timedelta(days=1))
    turnos = {t.id: t.codigo for t in repo.turnos_de_modulo(db, modulo.id)}
    nombres = repo.usernames(db, (r.creado_por for r in registros))
    return {
        "modulo_id": modulo.id, "desde": desde, "hasta": hasta,
        "registros": [_registro(r, turnos, nombres) for r in registros],
    }


def versiones(db: Session, turno_id: int, fecha: dt.date) -> list[dict[str, Any]]:
    """Todas las versiones del turno-día (la 1 es el original), de la más antigua a la vigente."""
    turno = db.get(Turno, turno_id)
    if turno is None:
        raise NoEncontrado("No existe el turno indicado.")
    registros = repo.versiones_turno_dia(db, turno.id, fecha)
    nombres = repo.usernames(db, (r.creado_por for r in registros))
    return [_registro(r, {turno.id: turno.codigo}, nombres, con_version=True) for r in registros]


def hora_minuto(minuto: float) -> str:
    """HH:MM del minuto, truncando los segundos y envolviendo a las 24 horas."""
    minutos = int(minuto) % 1440
    return f"{minutos // 60:02d}:{minutos % 60:02d}"


def validar_ciclo(inicio: float, duracion: float, m3ha: float) -> None:
    if not all(math.isfinite(v) for v in (inicio, duracion, m3ha)):
        raise DatosInvalidos("Los valores del ciclo deben ser números finitos")
    if not 0 < m3ha <= 100:
        raise DatosInvalidos("El riego debe ser mayor que 0 y como máximo 100 m³/ha")
    if not 0 <= inicio < 2880:
        raise DatosInvalidos("El inicio debe estar entre 0 y menos de 2880 minutos")
    if not 0 < duracion <= 1440:
        raise DatosInvalidos("La duración debe ser mayor que 0 y como máximo 1440 minutos")


def validar_aplicable(fecha: dt.date, fines_min: list[float]) -> None:
    """Aplicado = riego ya ocurrido: días pasados, u hoy si terminó el último ciclo (hora de Lima)."""
    hoy = hoy_lima()
    if fecha > hoy:
        raise DatosInvalidos("Un riego de un día futuro no se puede marcar aplicado")
    if fecha == hoy and fines_min:
        ahora = ahora_lima()
        ultimo = max(fines_min)
        if ultimo > ahora.hour * 60 + ahora.minute:
            raise DatosInvalidos(
                "El riego de hoy se puede marcar aplicado cuando termine su último ciclo "
                f"({hora_minuto(ultimo)}{' del día siguiente' if ultimo >= 1440 else ''})"
            )


def eliminar(db: Session, registro_id: int, motivo: str, actor: Usuario,
             contexto: ContextoPeticion | None = None) -> dict[str, Any]:
    """Quita el riego vigente del turno-día (queda «sin registro»).

    Las versiones no se borran: la vigente deja de serlo y sigue en el historial; el motivo
    queda en la auditoría. Para corregir datos se usa «Editar riego»; esto es para un registro
    que no debió existir.
    """
    if actor.rol not in (RolUsuario.admin, RolUsuario.encargado, RolUsuario.subgerente):
        raise SinPermiso()
    motivo = motivo.strip()
    if not 1 <= len(motivo) <= 255:
        raise DatosInvalidos("El motivo debe tener entre 1 y 255 caracteres")
    registro = db.get(RiegoRegistro, registro_id)
    if registro is None:
        raise NoEncontrado("No existe el registro de riego indicado.")
    # Mismo orden de candados que la edición manual: cronograma del día y luego turno-día.
    crono = repo_cronogramas.por_fecha(db, registro.modulo_id, registro.fecha)
    if crono is not None:
        repo_cronogramas.obtener(db, crono.id, bloquear=True)
    vigente = repo.bloquear_turno_dia(db, registro.turno_id, registro.fecha)
    if vigente is None or vigente.id != registro.id:
        raise Conflicto("Otro usuario cambió este riego; recarga")
    repo.dejar_de_ser_vigentes(db, [vigente.id])
    detalle = {"turno_id": vigente.turno_id, "fecha": vigente.fecha, "version": vigente.version,
               "estado": vigente.estado.value, "origen": vigente.origen.value, "motivo": motivo}
    auditoria_service.registrar(db, accion="riego_eliminado", entidad="riego", entidad_id=vigente.id,
                                actor=actor, contexto=contexto, detalle=detalle)
    return {"turno_id": vigente.turno_id, "fecha": vigente.fecha, "version": vigente.version}


def _crear_registro(db: Session, *, turno: Turno, fecha: dt.date, vigente: RiegoRegistro | None,
                    ciclos: list[dict], estado: EstadoRiego, origen: OrigenRiego, actor: Usuario,
                    sin_riego: bool = False, cronograma_version_id: int | None = None,
                    motivo: str | None = None, comentario: str | None = None) -> RiegoRegistro:
    numero = repo.max_version_turno_dia(db, turno.id, fecha) + 1
    if vigente is not None:
        repo.dejar_de_ser_vigentes(db, [vigente.id])
    registro = RiegoRegistro(
        modulo_id=turno.modulo_id, turno_id=turno.id, fecha=fecha, version=numero, vigente=True,
        estado=estado, origen=origen, sin_riego=sin_riego, contenido_sha256=hash_contenido(ciclos, sin_riego),
        cronograma_version_id=cronograma_version_id, basado_en_id=vigente.id if vigente else None,
        motivo=motivo, comentario=comentario, creado_por=actor.id,
    )
    db.add(registro)
    db.flush()
    repo.insertar_ciclos(db, [{"registro_id": registro.id, **c} for c in ciclos])
    return registro


def sincronizar_provisional(db: Session, cronograma: Cronograma, version: CronogramaVersion,
                            actor: Usuario, *, solo_existentes: bool = False) -> list[str]:
    """El llamador mantiene FOR UPDATE del cronograma e incrementa su lock una sola vez.

    Publicar cambios usa solo_existentes; el Visto también crea donde no había riego.
    Los aplicados y provisionales manuales se conservan.
    """
    avisos, creados, actualizados = [], [], []
    turnos = {t.id: t for t in repo.turnos_de_modulo(db, cronograma.modulo_id)}
    for t in sorted(version.turnos, key=lambda t: t.turno_id):
        turno = turnos[t.turno_id]
        vigente = repo.bloquear_turno_dia(db, turno.id, cronograma.fecha)
        if vigente is not None and vigente.estado == EstadoRiego.aplicado:
            continue
        if vigente is not None and vigente.origen == OrigenRiego.manual:
            avisos.append(f"{turno.codigo}: el riego provisional fue editado a mano; se conservó")
            continue
        if vigente is not None and vigente.origen != OrigenRiego.cronograma:
            avisos.append(f"{turno.codigo}: el riego provisional tiene otro origen; se conservó")
            continue
        if solo_existentes and vigente is None:
            continue
        ciclos = [{k: getattr(c, k) for k in (
            "inicio_min", "fin_min", "duracion_min", "riego_m3", "riego_m3ha",
            "hora_inicio", "hora_fin", "fin_dia_siguiente",
        )} | {"area_ha": t.area_ha, "valvula": turno.valvula_controlador}
            for c in version.ciclos if c.turno_id == turno.id]
        if len({c["inicio_min"] for c in ciclos}) != len(ciclos):
            avisos.append(f"{turno.codigo}: hay ciclos con el mismo inicio; no se sincronizó el riego provisional")
            continue
        if vigente is not None and hash_contenido(ciclos) == vigente.contenido_sha256:
            continue
        _crear_registro(db, turno=turno, fecha=cronograma.fecha, vigente=vigente, ciclos=ciclos,
                        estado=EstadoRiego.provisional, origen=OrigenRiego.cronograma, actor=actor,
                        cronograma_version_id=version.id)
        (actualizados if vigente else creados).append(turno.id)
    # Un evento por acción; si hubo ambos efectos se clasifica como actualización.
    if creados or actualizados:
        tipo = (TipoEventoCronograma.riego_provisional_actualizado if actualizados
                else TipoEventoCronograma.riego_provisional_creado)
        db.add(CronogramaEvento(cronograma_id=cronograma.id, version_id=version.id, usuario_id=actor.id,
                                tipo=tipo, ocurrido_at=ahora_utc(),
                                detalle={"turnos": sorted(creados + actualizados)}))
    db.flush()
    return avisos


def guardar_manual(db: Session, datos: RegistroRiegoEntrada, actor: Usuario,
                    contexto: ContextoPeticion | None = None) -> dict[str, Any]:
    if actor.rol not in (RolUsuario.admin, RolUsuario.encargado, RolUsuario.subgerente):
        raise SinPermiso()
    turno = db.get(Turno, datos.turno_id)
    if turno is None:
        raise NoEncontrado("No existe el turno indicado.")
    if fuera_de_limites(datos.fecha) is not None:
        raise DatosInvalidos(mensaje_fuera_de_limites())
    if datos.estado == EstadoRiego.aplicado:
        validar_aplicable(datos.fecha, [c.inicio_min + c.duracion_min for c in datos.ciclos])
    if (datos.sin_riego and datos.ciclos) or (
            not datos.sin_riego and not 1 <= len(datos.ciclos) <= calculo_pulsos.MAX_PULSOS_TURNO):
        raise DatosInvalidos(
            f"Indica de 1 a {calculo_pulsos.MAX_PULSOS_TURNO} ciclos, o una lista vacía si no se regó")
    motivo = datos.motivo.strip()
    if not 1 <= len(motivo) <= 255:
        raise DatosInvalidos("El motivo debe tener entre 1 y 255 caracteres")
    crono = repo_cronogramas.por_fecha(db, turno.modulo_id, datos.fecha)
    if crono is not None:
        crono = repo_cronogramas.obtener(db, crono.id, bloquear=True)
    vigente = repo.bloquear_turno_dia(db, turno.id, datos.fecha)
    if datos.basado_en_id != (vigente.id if vigente else None):
        raise Conflicto("Otro usuario cambió este riego; recarga")
    ciclos = []
    for c in datos.ciclos:
        validar_ciclo(c.inicio_min, c.duracion_min, c.riego_m3ha)
        inicio, duracion, m3ha = round(c.inicio_min, 1), round(c.duracion_min, 1), round(c.riego_m3ha, 2)
        validar_ciclo(inicio, duracion, m3ha)
        fin = round(inicio + duracion, 1)
        ciclos.append({"inicio_min": inicio, "fin_min": fin, "duracion_min": duracion,
                       "riego_m3ha": m3ha, "riego_m3": round(m3ha * turno.area_ha, 1), "area_ha": turno.area_ha,
                       "valvula": turno.valvula_controlador, "hora_inicio": hora_minuto(inicio),
                       "hora_fin": hora_minuto(fin), "fin_dia_siguiente": fin >= 1440})
    if len({c["inicio_min"] for c in ciclos}) != len(ciclos):
        raise DatosInvalidos("Los ciclos de riego no pueden repetir el minuto de inicio")
    if vigente and vigente.estado == datos.estado and vigente.contenido_sha256 == hash_contenido(ciclos, datos.sin_riego):
        raise DatosInvalidos("No hay cambios")
    registro = _crear_registro(db, turno=turno, fecha=datos.fecha, vigente=vigente, ciclos=ciclos,
                               estado=datos.estado, origen=OrigenRiego.manual, actor=actor,
                               sin_riego=datos.sin_riego, motivo=motivo, comentario=datos.comentario)
    marcado = datos.estado == EstadoRiego.aplicado and (vigente is None or vigente.estado != EstadoRiego.aplicado)
    accion = "riego_sin_riego" if datos.sin_riego else (
        "riego_marcado_aplicado" if vigente and marcado else "riego_editado"
    )
    auditoria_service.registrar(db, accion=accion, entidad="riego", entidad_id=registro.id, actor=actor,
                                contexto=contexto, detalle={"turno_id": turno.id, "fecha": datos.fecha,
                                                           "version": registro.version, "motivo": motivo})
    if crono is not None and marcado:
        db.add(CronogramaEvento(
            cronograma_id=crono.id, version_id=crono.version_publicada_id or crono.borrador_version_id,
            usuario_id=actor.id, tipo=TipoEventoCronograma.riego_marcado_aplicado, ocurrido_at=ahora_utc(),
            comentario=motivo, detalle={"turno_id": turno.id, "registro_id": registro.id},
        ))
        crono.lock_version += 1
    db.flush()
    return _registro(registro, {turno.id: turno.codigo}, {actor.id: actor.username})
