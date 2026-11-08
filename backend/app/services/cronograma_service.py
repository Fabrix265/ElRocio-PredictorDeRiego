"""Generación, regeneración y lectura de cronogramas (§3.1–§3.3; F3).

Generar (por cada día de la ventana):
- sin cronograma → Borrador con v1 ``origen=modelo``;
- Borrador cuyo borrador es del modelo o regenerado (sin correcciones) → versión ``regenerado``;
- Borrador con correcciones, o Publicado / Visto / Corrección solicitada → se omite, salvo
  ``regenerar_existentes``: entonces la versión ``regenerado`` queda como borrador (de cambios).

El bucle está en ``app.ml.generador`` (idéntico a ``planificar`` con días nuevos). Se serializa por
módulo: candado del modelo en el proceso + candado de transacción en la BD → 409 si hay otra.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from dataclasses import dataclass
from typing import Any

import pandas as pd
from riego_ml.utils.tiempo import norm_text
from sqlalchemy.orm import Session

from app.core.errores import Conflicto, DatosInvalidos, NoEncontrado
from app.core.tiempo import hoy_lima
from app.ml import generador
from app.ml.historial_bd import construir_historial
from app.ml.model_loader import CANDADO_MODELO, cargar_modelo, registrar_version
from app.models import (
    Cronograma,
    CronogramaEvento,
    CronogramaVersion,
    Generacion,
    Modulo,
    PrediccionEntrada,
    Usuario,
)
from app.models.enums import (
    EstadoCronograma,
    OrigenRiegoD1,
    OrigenVersion,
    RolUsuario,
    TipoEventoCronograma,
    TipoGeneracion,
)
from app.repositories import cronogramas as repo
from app.repositories import riego as repo_riego
from app.services import auditoria_service, datos_service
from app.services.contexto import ContextoPeticion

logger = logging.getLogger(__name__)

DIAS_POR_DEFECTO = 3
DIAS_MAX = 7
DIAS_ATRAS_MAX = 7
MIN_DIAS_RIEGO = 45
ESPERA_CANDADO_S = 30
ORIGENES_SIN_CORRECCION = (OrigenVersion.modelo, OrigenVersion.regenerado)
ESTADOS_PUBLICADOS = (EstadoCronograma.publicado, EstadoCronograma.visto, EstadoCronograma.correccion_solicitada)


@dataclass
class Accion:
    fecha: dt.date
    cronograma: Cronograma | None
    tipo: str  # crear · regenerar · regenerar_cambios · omitir
    mensaje: str | None = None


# --- Generar ---------------------------------------------------------------------

def _validar(db: Session, modulo_id: int, fecha_inicio: dt.date, dias: int) -> Modulo:
    modulo = db.get(Modulo, modulo_id)
    if modulo is None:
        raise NoEncontrado("Módulo no encontrado")
    hoy = hoy_lima()
    if not hoy - dt.timedelta(days=DIAS_ATRAS_MAX) <= fecha_inicio <= hoy + dt.timedelta(days=1):
        raise DatosInvalidos(
            f"La fecha inicial debe estar entre {hoy - dt.timedelta(days=DIAS_ATRAS_MAX):%d/%m/%Y} "
            f"y mañana ({hoy + dt.timedelta(days=1):%d/%m/%Y})."
        )
    if not 1 <= dias <= DIAS_MAX:
        raise DatosInvalidos(f"El número de días debe estar entre 1 y {DIAS_MAX}.")
    if repo.dias_con_riego_antes(db, modulo_id, fecha_inicio) < MIN_DIAS_RIEGO:
        raise DatosInvalidos(
            f"Faltan datos: se necesitan al menos {MIN_DIAS_RIEGO} días de riego registrados antes de la fecha inicial."
        )
    return modulo


def _decidir(db: Session, existentes: dict[dt.date, Cronograma], fechas: list[dt.date], *,
             regenerar_existentes: bool, forzar: bool, confirmar: bool) -> list[Accion]:
    borradores = repo.versiones_por_id(db, [c.borrador_version_id for c in existentes.values()])
    acciones = []
    for fecha in fechas:
        crono = existentes.get(fecha)
        if crono is None:
            acciones.append(Accion(fecha, None, "crear"))
            continue
        borrador = borradores.get(crono.borrador_version_id)
        corregido = borrador is not None and borrador.origen not in ORIGENES_SIN_CORRECCION
        if crono.estado == EstadoCronograma.borrador and not corregido:
            acciones.append(Accion(fecha, crono, "regenerar"))
        elif regenerar_existentes or forzar:
            if corregido and forzar and not confirmar:
                raise Conflicto(
                    "El borrador tiene correcciones: regenerar crea una versión nueva del modelo sobre ellas. "
                    "Confirma para continuar."
                )
            acciones.append(Accion(fecha, crono, "regenerar_cambios"))
        else:
            acciones.append(Accion(fecha, crono, "omitir", "Existe; use Regenerar en el detalle."))
    return acciones


def _datos_incompletos(frescura: Any) -> bool:
    """§3.3: alguna fuente sin D-1 al generar, o huecos de riego por turno en D-7..D-1.

    Para el riego cuenta lo conocido de D-1 (aplicado o provisional: fuente ``riego_provisional``);
    el aplicado suele llegar con días de atraso (Excel semanal) y no marca incompleto por sí solo.
    """
    limite = frescura.referencia - dt.timedelta(days=6)
    for fuente in frescura.fuentes:
        if fuente.informativa or fuente.fuente == "riego_aplicado":
            continue
        if fuente.estado != "verde":
            return True
        if fuente.fuente == "riego_provisional":
            huecos = list(fuente.huecos) + [h for t in (fuente.por_turno or []) for h in t.huecos]
            if any(h >= limite for h in huecos):
                return True
    return False


def _ambiente_completo(historial: Any, fecha: pd.Timestamp) -> bool:
    amb = historial.ambiente
    fila = amb[amb["Fecha"] == fecha]
    if fila.empty:
        return False
    columnas = [c for c in ("tiene_meteo", "tiene_suelo", "tiene_planta") if c in fila]
    return bool(columnas) and bool((fila[columnas].fillna(0).iloc[0] == 1).all())


def _fuentes_hasta(frescura: Any) -> dict[str, Any]:
    return {f.fuente: f.ultima_fecha.isoformat() if f.ultima_fecha else None for f in frescura.fuentes}


def generar(
    db: Session, *, modulo_id: int, fecha_inicio: dt.date, dias: int, regenerar_existentes: bool,
    actor: Usuario, contexto: ContextoPeticion | None = None, tipo: TipoGeneracion = TipoGeneracion.generar,
    forzar: bool = False, confirmar: bool = False,
) -> dict[str, Any]:
    inicio_reloj = time.monotonic()
    modulo = _validar(db, modulo_id, fecha_inicio, dias)
    fechas = [fecha_inicio + dt.timedelta(days=i) for i in range(dias)]

    if not CANDADO_MODELO.acquire(timeout=ESPERA_CANDADO_S):
        raise Conflicto("El modelo está ocupado con otra generación. Intenta de nuevo en unos segundos.")
    try:
        if not repo.tomar_candado_generacion(db, modulo_id):
            raise Conflicto("Ya hay una generación en curso para este módulo. Intenta de nuevo en unos segundos.")
        modelo = cargar_modelo()
        from riego_ml.config import load_config

        config = load_config()
        existentes = repo.bloquear_rango(db, modulo_id, fechas)
        acciones = _decidir(db, existentes, fechas, regenerar_existentes=regenerar_existentes,
                            forzar=forzar, confirmar=confirmar)

        frescura = datos_service.frescura(db, modulo_id, fecha_inicio)
        incompletos = _datos_incompletos(frescura)
        hb = construir_historial(db, modulo_id, hasta=fechas[-1] + dt.timedelta(days=1))
        historial = hb.historial
        desde_cronograma = set(hb.turno_dias_cronograma)
        modelo_id = registrar_version(db, modelo)
        turnos = {norm_text(pd.Series([t.codigo])).iloc[0]: t for t in repo_riego.turnos_de_modulo(db, modulo_id)}
        estados_d1 = repo.estado_registros(db, modulo_id, [f - dt.timedelta(days=1) for f in fechas])

        generacion = Generacion(
            modulo_id=modulo_id, fecha_inicio=fecha_inicio, dias=dias, tipo=tipo, usuario_id=actor.id,
            modelo_version_id=modelo_id, frescura=generador.json_seguro(frescura.model_dump(mode="json")),
            resultado_por_dia=[],
        )
        db.add(generacion)
        db.flush()

        hoy = hoy_lima()
        resultado = []
        generados: set[dt.date] = set()
        for i, accion in enumerate(acciones):
            if accion.tipo == "omitir":
                resultado.append(_fila_resultado(accion, None))
                continue
            fecha = accion.fecha
            d1 = fecha - dt.timedelta(days=1)
            prediccion = generador.predecir_dia(modelo.plan, historial, fecha, config)
            historial = generador.agregar(historial, prediccion)

            origen_d1: dict[int, OrigenRiegoD1] = {}
            for codigo, turno in turnos.items():
                estado = estados_d1.get((turno.id, d1))
                if d1 in generados or (d1 in fechas and estado is None):
                    origen_d1[turno.id] = OrigenRiegoD1.cronograma
                elif estado is not None:
                    origen_d1[turno.id] = OrigenRiegoD1(estado)
                elif (d1, codigo) in desde_cronograma:
                    origen_d1[turno.id] = OrigenRiegoD1.cronograma
                else:
                    origen_d1[turno.id] = OrigenRiegoD1.ninguno
            preliminar = (
                i > 0 or fecha > hoy
                or any(o == OrigenRiegoD1.cronograma for o in origen_d1.values())
                or not _ambiente_completo(historial, pd.Timestamp(d1))
            )
            version = _guardar(db, accion, prediccion, turnos, modulo, generacion, modelo_id, actor,
                               preliminar=preliminar, datos_incompletos=incompletos)
            for codigo, turno in turnos.items():
                if codigo not in prediccion.features_turno:
                    continue
                db.add(PrediccionEntrada(
                    generacion_id=generacion.id, fecha=fecha, turno_id=turno.id, modelo_version_id=modelo_id,
                    features_turno=prediccion.features_turno[codigo],
                    features_ciclo=prediccion.features_ciclo.get(codigo, []),
                    alternativas_n={str(n): c for n, c in prediccion.alternativas.get(codigo, {}).items()},
                    origen_riego_d1=origen_d1[turno.id], fuentes_hasta=_fuentes_hasta(frescura),
                ))
            generados.add(fecha)
            resultado.append(_fila_resultado(accion, version))

        generacion.resultado_por_dia = generador.json_seguro(resultado)
        generacion.duracion_ms = int((time.monotonic() - inicio_reloj) * 1000)
        db.flush()
    finally:
        CANDADO_MODELO.release()

    return {
        "generacion_id": generacion.id, "modulo_id": modulo_id, "fecha_inicio": fecha_inicio, "dias": dias,
        "modelo_version": modelo.version, "dias_resultado": resultado,
        "frescura": frescura, "duracion_ms": generacion.duracion_ms,
    }


def _fila_resultado(accion: Accion, version: CronogramaVersion | None) -> dict[str, Any]:
    textos = {"crear": "creado", "regenerar": "regenerado", "regenerar_cambios": "regenerado", "omitir": "omitido"}
    return {
        "fecha": accion.fecha,
        "accion": textos[accion.tipo],
        "cronograma_id": version.cronograma_id if version else (accion.cronograma.id if accion.cronograma else None),
        "version": version.numero if version else None,
        "borrador_de_cambios": accion.tipo == "regenerar_cambios"
        and accion.cronograma is not None and accion.cronograma.estado != EstadoCronograma.borrador,
        "preliminar": version.preliminar if version else None,
        "datos_incompletos": version.datos_incompletos if version else None,
        "mensaje": accion.mensaje,
    }


def _guardar(
    db: Session, accion: Accion, prediccion: generador.PrediccionDia, turnos: dict, modulo: Modulo,
    generacion: Generacion, modelo_id: int, actor: Usuario, *, preliminar: bool, datos_incompletos: bool,
) -> CronogramaVersion:
    crono = accion.cronograma
    if crono is None:
        crono = Cronograma(modulo_id=modulo.id, fecha=accion.fecha, estado=EstadoCronograma.borrador)
        db.add(crono)
        db.flush()
        numero, origen, base = 1, OrigenVersion.modelo, None
    else:
        numero = repo.max_numero(db, crono.id) + 1
        origen = OrigenVersion.regenerado
        base = crono.borrador_version_id or crono.version_publicada_id

    version = CronogramaVersion(
        cronograma_id=crono.id, numero=numero, origen=origen, generacion_id=generacion.id,
        modelo_version_id=modelo_id, basada_en_id=base, preliminar=preliminar,
        datos_incompletos=datos_incompletos, creado_por=actor.id,
    )
    db.add(version)
    db.flush()

    filas_turno, filas_ciclo = [], []
    for turno_ml, g in prediccion.plan.groupby("Turno", sort=True):
        turno = turnos.get(turno_ml)
        if turno is None:
            logger.warning("El modelo devolvió un turno que no existe en el módulo: %s", turno_ml)
            continue
        n = int(g["n_ciclos"].iloc[0])
        factor = prediccion.factor.get(turno_ml)
        area = float((g["riego_m3"] / g["riego_m3ha"]).iloc[0]) if float(g["riego_m3ha"].iloc[0]) else turno.area_ha
        filas_turno.append({
            "version_id": version.id, "turno_id": turno.id, "n_ciclos": n, "n_ciclos_modelo": n,
            "factor_min_por_m3ha": factor, "area_ha": area,
            "caudal_m3h": (area * 60.0 / factor) if factor else None,
        })
        for c in generador.ciclos_de(g):
            filas_ciclo.append({
                "version_id": version.id, "turno_id": turno.id, "ciclo": c["ciclo"],
                "riego_m3ha": c["riego_m3ha"], "riego_m3": c["riego_m3"], "duracion_min": c["duracion_min"],
                "inicio_min": c["inicio_min"], "fin_min": c["fin_min"], "hora_inicio": c["hora_inicio"],
                "hora_fin": c["hora_fin"], "fin_dia_siguiente": c["fin_dia_siguiente"],
                "m3ha_p10": c["m3ha_p10"], "m3ha_p90": c["m3ha_p90"],
                "duracion_p10": c["duracion_p10"], "duracion_p90": c["duracion_p90"],
                "inicio_desde_min": c["inicio_desde_min"], "inicio_hasta_min": c["inicio_hasta_min"],
                "ciclo_modelo": c["ciclo"], "duracion_manual": False, "campos_editados": [],
            })
    repo.insertar_turnos(db, filas_turno)
    repo.insertar_ciclos(db, filas_ciclo)

    crono.borrador_version_id = version.id
    crono.lock_version = (crono.lock_version or 1) + (0 if numero == 1 else 1)
    evento = TipoEventoCronograma.generado if numero == 1 else TipoEventoCronograma.regenerado
    db.add(CronogramaEvento(cronograma_id=crono.id, version_id=version.id, tipo=evento, usuario_id=actor.id,
                            detalle={"generacion_id": generacion.id, "version": numero}))
    auditoria_service.registrar(
        db, accion="generar" if numero == 1 else "regenerar", entidad="cronograma", entidad_id=crono.id,
        actor=actor, detalle={"modulo": modulo.codigo, "fecha": accion.fecha.isoformat(), "version": numero,
                              "generacion_id": generacion.id, "preliminar": preliminar,
                              "datos_incompletos": datos_incompletos},
    )
    db.flush()
    return version


def regenerar(db: Session, cronograma_id: int, *, confirmar: bool, actor: Usuario,
              contexto: ContextoPeticion | None = None) -> dict[str, Any]:
    crono = repo.obtener(db, cronograma_id)
    if crono is None:
        raise NoEncontrado("Cronograma no encontrado")
    return generar(db, modulo_id=crono.modulo_id, fecha_inicio=crono.fecha, dias=1, regenerar_existentes=True,
                   actor=actor, contexto=contexto, tipo=TipoGeneracion.regenerar, forzar=True, confirmar=confirmar)


# --- Lectura ---------------------------------------------------------------------

def _es_programador(usuario: Usuario) -> bool:
    return usuario.rol == RolUsuario.programador


def _visible(crono: Cronograma, usuario: Usuario) -> None:
    if _es_programador(usuario) and crono.version_publicada_id is None:
        raise NoEncontrado("Cronograma no encontrado")


def _version_salida(db: Session, version: CronogramaVersion, crono: Cronograma, modulo: Modulo, *,
                    con_detalle: bool = True) -> dict[str, Any]:
    nombres = repo_riego.usernames(db, [version.creado_por, version.publicada_por])
    modelos = repo.nombres_modelo(db, [version.modelo_version_id])
    salida: dict[str, Any] = {
        "id": version.id, "numero": version.numero, "origen": version.origen.value,
        "creado_at": version.created_at, "creado_por": nombres.get(version.creado_por),
        "preliminar": version.preliminar, "datos_incompletos": version.datos_incompletos,
        "regenerado": version.origen == OrigenVersion.regenerado,
        "publicada_at": version.publicada_at, "publicada_por": nombres.get(version.publicada_por),
        "es_borrador": version.id == crono.borrador_version_id,
        "es_publicada": version.id == crono.version_publicada_id,
        "modelo_version": modelos.get(version.modelo_version_id),
        "generacion_id": version.generacion_id,
        "motivo_codigo": version.motivo_codigo, "motivo_comentario": version.motivo_comentario,
    }
    if not con_detalle:
        return salida
    salida["desactualizado"] = repo.desactualizado(db, modulo, crono.fecha, version.created_at)
    turnos = {t.id: t for t in repo_riego.turnos_de_modulo(db, modulo.id)}
    ciclos: dict[int, list] = {}
    for c in version.ciclos:
        ciclos.setdefault(c.turno_id, []).append(c)
    filas = []
    for t in sorted(version.turnos, key=lambda x: (turnos[x.turno_id].orden if x.turno_id in turnos else 0)):
        lista = sorted(ciclos.get(t.turno_id, []), key=lambda c: c.ciclo)
        filas.append({
            "turno_id": t.turno_id, "turno_codigo": turnos[t.turno_id].codigo if t.turno_id in turnos else "?",
            "n_ciclos": t.n_ciclos, "n_ciclos_modelo": t.n_ciclos_modelo, "area_ha": t.area_ha,
            "factor_min_por_m3ha": t.factor_min_por_m3ha, "caudal_m3h": t.caudal_m3h,
            "total_m3ha": round(sum(c.riego_m3ha for c in lista), 2),
            "total_m3": round(sum(c.riego_m3 for c in lista), 1),
            "total_min": round(sum(c.duracion_min for c in lista), 1),
            "ciclos": [{
                "ciclo": c.ciclo, "riego_m3ha": c.riego_m3ha, "riego_m3": c.riego_m3,
                "duracion_min": c.duracion_min, "inicio_min": c.inicio_min, "fin_min": c.fin_min,
                "hora_inicio": c.hora_inicio, "hora_fin": c.hora_fin, "fin_dia_siguiente": c.fin_dia_siguiente,
                "m3ha_p10": c.m3ha_p10, "m3ha_p90": c.m3ha_p90,
                "inicio_desde_min": c.inicio_desde_min, "inicio_hasta_min": c.inicio_hasta_min,
            } for c in lista],
        })
    salida["turnos"] = filas
    salida["total_m3"] = round(sum(f["total_m3"] for f in filas), 1)
    return salida


def _cabecera(crono: Cronograma, modulo: Modulo) -> dict[str, Any]:
    return {
        "id": crono.id, "modulo_id": modulo.id, "modulo_codigo": modulo.codigo, "fecha": crono.fecha,
        "estado": crono.estado.value, "lock_version": crono.lock_version,
        "num_publicaciones": crono.num_publicaciones,
        "version_publicada_id": crono.version_publicada_id,
        "borrador_version_id": crono.borrador_version_id,
        "tiene_borrador_cambios": crono.borrador_version_id is not None and crono.estado in ESTADOS_PUBLICADOS,
        "actualizado_at": crono.updated_at,
    }


def detalle(db: Session, cronograma_id: int, usuario: Usuario) -> dict[str, Any]:
    crono = repo.obtener(db, cronograma_id)
    if crono is None:
        raise NoEncontrado("Cronograma no encontrado")
    return _detalle(db, crono, usuario)


def _detalle(db: Session, crono: Cronograma, usuario: Usuario) -> dict[str, Any]:
    _visible(crono, usuario)
    modulo = db.get(Modulo, crono.modulo_id)
    if _es_programador(usuario):
        version_id = crono.version_publicada_id
    else:
        version_id = crono.borrador_version_id or crono.version_publicada_id
    version = repo.version(db, version_id)
    salida = _cabecera(crono, modulo)
    salida["version"] = _version_salida(db, version, crono, modulo) if version else None
    salida["versiones"] = versiones(db, crono.id, usuario, crono=crono, modulo=modulo)
    return salida


def por_fecha(db: Session, modulo_id: int, fecha: dt.date, usuario: Usuario) -> dict[str, Any] | None:
    datos_service.validar_fechas(fecha)
    crono = repo.por_fecha(db, modulo_id, fecha)
    if crono is None or (_es_programador(usuario) and crono.version_publicada_id is None):
        return None
    return _detalle(db, crono, usuario)


def versiones(db: Session, cronograma_id: int, usuario: Usuario, *, crono: Cronograma | None = None,
              modulo: Modulo | None = None) -> list[dict[str, Any]]:
    crono = crono or repo.obtener(db, cronograma_id)
    if crono is None:
        raise NoEncontrado("Cronograma no encontrado")
    _visible(crono, usuario)
    modulo = modulo or db.get(Modulo, crono.modulo_id)
    lista = repo.versiones(db, crono.id)
    if _es_programador(usuario):
        lista = [v for v in lista if v.publicada_at is not None]
    return [_version_salida(db, v, crono, modulo, con_detalle=False) for v in lista]


def version(db: Session, cronograma_id: int, numero: int, usuario: Usuario) -> dict[str, Any]:
    crono = repo.obtener(db, cronograma_id)
    if crono is None:
        raise NoEncontrado("Cronograma no encontrado")
    _visible(crono, usuario)
    v = repo.version_por_numero(db, crono.id, numero)
    if v is None or (_es_programador(usuario) and v.publicada_at is None):
        raise NoEncontrado("Versión no encontrada")
    return _version_salida(db, v, crono, db.get(Modulo, crono.modulo_id))


def listar(db: Session, modulo_id: int, desde: dt.date | None, hasta: dt.date | None,
           estado: str | None, usuario: Usuario) -> list[dict[str, Any]]:
    datos_service.modulo_o_404(db, modulo_id)
    datos_service.validar_fechas(desde, hasta)
    hoy = hoy_lima()
    hasta = hasta or hoy + dt.timedelta(days=DIAS_MAX)
    desde = desde or hasta - dt.timedelta(days=44)
    if desde > hasta:
        raise DatosInvalidos("«desde» debe ser anterior o igual a «hasta»")
    if (hasta - desde).days + 1 > 92:
        raise DatosInvalidos("El rango no puede superar 92 días")
    filtro = None
    if estado:
        try:
            filtro = EstadoCronograma(estado)
        except ValueError:
            raise DatosInvalidos("Estado de cronograma desconocido.") from None
    modulo = db.get(Modulo, modulo_id)
    cronos = repo.listar(db, modulo_id, desde, hasta, solo_publicados=_es_programador(usuario), estado=filtro)
    if _es_programador(usuario):
        refs = {c.id: c.version_publicada_id for c in cronos}
    else:
        refs = {c.id: c.borrador_version_id or c.version_publicada_id for c in cronos}
    versiones_ref = repo.versiones_por_id(db, refs.values())
    salida = []
    for c in cronos:
        v = versiones_ref.get(refs[c.id])
        fila = _cabecera(c, modulo)
        fila["version"] = None if v is None else {
            "id": v.id, "numero": v.numero, "origen": v.origen.value, "creado_at": v.created_at,
            "preliminar": v.preliminar, "datos_incompletos": v.datos_incompletos,
            "regenerado": v.origen == OrigenVersion.regenerado,
        }
        salida.append(fila)
    return salida

