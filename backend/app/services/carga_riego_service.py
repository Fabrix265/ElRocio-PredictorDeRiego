"""Carga de Excel de riego (hoja MOD5) con vista previa y confirmación (§3.5, decisión D7).

Flujo: subir (validación del archivo en :mod:`app.services.archivo_excel`) → vista previa por
turno-día → marcar/desmarcar grupos → confirmar o descartar.

**Vista previa.** Las filas se leen con ``leer_riego`` (en memoria) y se normalizan con
``limpiar_ciclos(…, 5 min, 2 m3/ha)``, igual que la carga histórica y el Historial (§2.3). Cada
turno-día se compara con el registro vigente por hash de contenido
(:func:`app.services.riego_contenido.hash_contenido`):

=========================  =============================================================  ==========
Resultado                  Cuándo                                                         Marcado
=========================  =============================================================  ==========
``igual``                  mismo contenido que el vigente (no crea versión)               no aplica
``nuevo``                  el turno-día no tiene registro                                 sí
``reemplaza_provisional``  el vigente es provisional                                      sí
``reemplaza_aplicado``     el vigente ya es aplicado                                      sí, salvo
                                                                                          vigente
                                                                                          manual
``sin_riego``              D7: el archivo trae la fecha pero ninguna fila del turno, o    sí, salvo
                           solo aperturas fallidas → "no se regó"                         vigente
                                                                                          aplicado
``error``                  fecha de hoy o futura, turno o válvula desconocidos, inicio    no aplica
                           repetido con valores distintos, fila de otro fundo/módulo
=========================  =============================================================  ==========

**Confirmar.** Bloquea la carga y los registros vigentes del rango (``FOR UPDATE``). Si pasaron
24 h o cambió algún registro comparado (otro usuario o carga creó una versión), la carga **vence**
y se pide subirla otra vez (409). Lo marcado queda como versión nueva ``aplicado`` origen
``excel`` (la anterior pasa a ``vigente = false``; nunca se borra) y se audita. Subir otra vez el
archivo acumulado completo solo da "igual" para lo ya cargado.

Convención de transacciones: los servicios hacen ``flush`` y confirma quien llama. **Excepción
documentada**: al vencer una carga se confirma ese cambio de estado antes de responder 409, para
que la carga quede vencida aunque la petición termine en error.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from riego_ml.dataset.limpieza import limpiar_ciclos
from riego_ml.sources.riego import leer_riego
from riego_ml.utils.tiempo import minutes_to_hhmm, norm_text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errores import Conflicto, DatosInvalidos, NoEncontrado
from app.core.tiempo import ahora_utc, hoy_lima
from app.ml.historial_bd import MIN_DURACION_MIN, MIN_RIEGO_M3HA
from app.models import CargaRiego, Fundo, Modulo, Turno, Usuario
from app.models.enums import EstadoCarga, EstadoRiego, OrigenRiego, ResultadoCarga
from app.repositories import riego as repo
from app.services import ambiente_service, auditoria_service
from app.services.archivo_excel import MAX_FILAS, ArchivoInvalido, ArchivoValidado
from app.services.contexto import ContextoPeticion
from app.services.riego_contenido import ciclos_para_bd, hash_contenido, texto_valvula

HOJA = "MOD5"
VIGENCIA = dt.timedelta(hours=24)
MOTIVO_EXCEL = "Carga de Excel"
MOTIVO_SIN_RIEGO = "Carga de Excel: no se regó"
SIN_FILAS = f"La hoja {HOJA} no trae filas de riego válidas (con fecha, turno y hora de inicio)."

RESULTADOS_APLICABLES = frozenset({
    ResultadoCarga.nuevo, ResultadoCarga.reemplaza_provisional, ResultadoCarga.reemplaza_aplicado,
    ResultadoCarga.sin_riego,
})

MENSAJE_VENCIDA = (
    "La vista previa venció: pasaron 24 horas o alguien cambió uno de los registros comparados. "
    "Sube el archivo otra vez."
)
MENSAJE_D7 = "El archivo trae esta fecha pero ninguna fila de este turno: se registra «no se regó» (D7)."
MENSAJE_SOLO_FALLIDAS = (
    "Solo aperturas fallidas (< {dur:g} min o < {m3:g} m3/ha): se registra «no se regó»."
)


class CargaVencida(Conflicto):
    detail = MENSAJE_VENCIDA


# --- Lectura y comparación --------------------------------------------------------

def leer_hoja(archivo: ArchivoValidado) -> tuple[pd.DataFrame, dict]:
    """Hoja MOD5 con ``leer_riego`` en memoria; columnas y filas validadas (422 con el motivo)."""
    try:
        crudos, diag = leer_riego(archivo.abrir(), HOJA)
    except ValueError as error:
        coincidencia = re.search(r"Faltan columnas.*?:\s*\[(.*)\]", str(error))
        if coincidencia:
            faltan = coincidencia.group(1).replace("'", "")
            raise ArchivoInvalido(f"A la hoja {HOJA} le faltan columnas: {faltan}.") from None
        if "NaT" in str(error):
            # leer_riego no puede armar el rango de fechas: no quedó ninguna fila válida.
            raise ArchivoInvalido(SIN_FILAS) from None
        raise ArchivoInvalido(f"No se pudo leer la hoja {HOJA} del archivo.") from None
    except Exception:  # noqa: BLE001 - cualquier fallo del parser es un archivo inválido
        raise ArchivoInvalido(f"No se pudo leer la hoja {HOJA} del archivo.") from None
    filas = int(diag.get("Riego: filas originales", len(crudos)))
    if filas > MAX_FILAS:
        raise ArchivoInvalido(f"La hoja {HOJA} supera el máximo de {MAX_FILAS:,} filas.".replace(",", " "))
    if crudos.empty:
        raise ArchivoInvalido(SIN_FILAS)
    return crudos, diag


@dataclass
class Grupo:
    """Un turno-día de la vista previa."""

    fecha: dt.date
    turno_id: int | None
    turno_codigo: str | None
    ciclos: list[dict[str, Any]] = field(default_factory=list)
    mensajes: list[str] = field(default_factory=list)
    error: bool = False
    sin_riego: bool = False
    resultado: ResultadoCarga | None = None
    aplicar: bool = False
    vigente_id: int | None = None

    @property
    def sha(self) -> str:
        return hash_contenido(self.ciclos, self.sin_riego)


def _nfc(valor: Any) -> str:
    return "" if valor is None or valor is pd.NA else unicodedata.normalize("NFC", str(valor))


def _ciclos_json(filas: pd.DataFrame) -> list[dict[str, Any]]:
    """Ciclos de un turno-día en el formato de ``riego_ciclo`` (para guardar y mostrar)."""
    return ciclos_para_bd(filas)


def agrupar(
    crudos: pd.DataFrame, modulo: Modulo, turnos: list[Turno], texto_fundo: str, hoy: dt.date
) -> tuple[list[Grupo], dict[str, Any]]:
    """Agrupa las filas por turno-día y detecta errores y "sin riego" (D7), sin comparar con la BD."""
    texto_modulo = str(norm_text(pd.Series([modulo.codigo])).iloc[0])
    por_codigo = {t.codigo.upper(): t for t in turnos}
    df = crudos.reset_index(drop=True).copy()
    df["_fecha"] = df["Fecha"].dt.date
    df["_turno"] = df["Turno"].map(_nfc)
    df["_fundo"] = df["Fundo"].map(_nfc)
    df["_modulo"] = df["Modulo"].map(_nfc)
    propios = (df["_fundo"] == _nfc(texto_fundo)) & (df["_modulo"] == _nfc(texto_modulo))

    grupos: list[Grupo] = []
    # Filas de otro fundo o módulo: error (los códigos de turno se repiten entre módulos).
    for (fecha, fundo_txt, modulo_txt, turno_txt), filas in df[~propios].groupby(
        ["_fecha", "_fundo", "_modulo", "_turno"], sort=True
    ):
        grupos.append(Grupo(
            fecha=fecha, turno_id=None, turno_codigo=turno_txt[:20] or None,
            ciclos=_ciclos_json(filas), error=True,
            mensajes=[f"Fila de otro fundo o módulo ({fundo_txt} / {modulo_txt}): no corresponde a "
                      f"{modulo.codigo}."],
        ))
    df = df[propios]

    mensajes: dict[tuple[dt.date, str], list[str]] = defaultdict(list)

    def _marcar(mascara: pd.Series, texto) -> None:
        for (fecha, turno), filas in df[mascara].groupby(["_fecha", "_turno"], sort=True):
            mensaje = texto(turno, filas) if callable(texto) else texto
            if mensaje not in mensajes[(fecha, turno)]:
                mensajes[(fecha, turno)].append(mensaje)

    desconocido = ~df["_turno"].isin(por_codigo)
    _marcar(desconocido, lambda turno, _f: f"Turno {turno} desconocido en {modulo.codigo}.")
    _marcar(df["_fecha"] >= hoy, "Fecha de hoy o futura: solo se carga el riego de días cerrados.")

    valvulas = df["Valvula"].map(texto_valvula)
    permitidas = df["_turno"].map(
        lambda c: {por_codigo[c].valvula_controlador, por_codigo[c].valvula_siga} if c in por_codigo else set()
    )
    valvula_mal = ~desconocido & valvulas.notna() & pd.Series(
        [v not in p for v, p in zip(valvulas, permitidas, strict=True)], index=df.index
    )
    _marcar(valvula_mal, lambda turno, filas: (
        f"Válvula {', '.join(sorted(set(valvulas[filas.index].dropna())))} no corresponde al turno "
        f"{turno} ({por_codigo[turno].valvula_controlador})."
    ))

    # Inicio repetido con valores distintos (los duplicados exactos los quita limpiar_ciclos).
    fallida = (
        df["duracion_min"].isna() | df["riego_m3ha"].isna()
        | (df["duracion_min"] < MIN_DURACION_MIN) | (df["riego_m3ha"] < MIN_RIEGO_M3HA)
    )
    validas = df[~fallida & ~desconocido]
    validas = validas[~validas.duplicated(["_fecha", "_turno", "inicio_min", "duracion_min", "riego_m3",
                                           "riego_m3ha"])]
    repetido = validas.duplicated(["_fecha", "_turno", "inicio_min"], keep=False)
    for (fecha, turno), filas in validas[repetido].groupby(["_fecha", "_turno"], sort=True):
        horas = ", ".join(sorted({minutes_to_hhmm(m) for m in filas["inicio_min"]}))
        mensajes[(fecha, turno)].append(f"Inicio {horas} repetido con valores distintos.")

    claves = pd.Series(list(zip(df["_fecha"], df["_turno"], strict=True)), index=df.index, dtype=object)
    con_error = claves.isin(set(mensajes))
    for (fecha, turno), filas in df[con_error].groupby(["_fecha", "_turno"], sort=True):
        turno_bd = por_codigo.get(turno)
        grupos.append(Grupo(
            fecha=fecha, turno_id=turno_bd.id if turno_bd else None, turno_codigo=turno[:20] or None,
            ciclos=_ciclos_json(filas), mensajes=mensajes[(fecha, turno)], error=True,
        ))

    # Turno-días válidos: limpiar_ciclos (aperturas fallidas y duplicados exactos fuera).
    sanos = df[~con_error]
    descartados_n = 0
    claves_con_grupo: set[tuple[dt.date, str]] = {(g.fecha, g.turno_codigo or "") for g in grupos
                                                    if g.turno_id is not None}
    if not sanos.empty:
        ciclos, descartados, _ = limpiar_ciclos(
            sanos.drop(columns=["_fecha", "_turno", "_fundo", "_modulo"]), MIN_DURACION_MIN, MIN_RIEGO_M3HA
        )
        descartados_n = len(descartados)
        ciclos["_fecha"] = ciclos["Fecha"].dt.date
        ciclos["_turno"] = ciclos["Turno"].map(_nfc)
        for (fecha, turno), filas in ciclos.groupby(["_fecha", "_turno"], sort=True):
            grupos.append(Grupo(fecha=fecha, turno_id=por_codigo[turno].id, turno_codigo=turno,
                                ciclos=_ciclos_json(filas)))
            claves_con_grupo.add((fecha, turno))
        mensaje_fallidas = MENSAJE_SOLO_FALLIDAS.format(dur=MIN_DURACION_MIN, m3=MIN_RIEGO_M3HA)
        for fecha, turno in sorted(set(zip(sanos["_fecha"], sanos["_turno"], strict=True)) - claves_con_grupo):
            grupos.append(Grupo(fecha=fecha, turno_id=por_codigo[turno].id, turno_codigo=turno,
                                sin_riego=True, mensajes=[mensaje_fallidas]))
            claves_con_grupo.add((fecha, turno))

    # D7: fecha presente en el archivo sin filas de un turno activo = "no se regó".
    fechas = sorted({f for f in df["_fecha"] if f < hoy})
    for fecha in fechas:
        for turno in turnos:
            if (fecha, turno.codigo.upper()) not in claves_con_grupo:
                grupos.append(Grupo(fecha=fecha, turno_id=turno.id, turno_codigo=turno.codigo,
                                    sin_riego=True, mensajes=[MENSAJE_D7]))

    grupos.sort(key=lambda g: (g.fecha, g.turno_codigo or "", g.turno_id or 0))
    resumen = {
        "ciclos_descartados": descartados_n,
        "fechas_en_archivo": len({f for f in crudos["Fecha"].dt.date}),
    }
    return grupos, resumen


def clasificar(grupos: list[Grupo], vigentes: dict[tuple[int, dt.date], Any]) -> None:
    """Fija ``resultado``, ``aplicar`` y ``vigente_id`` comparando con los registros vigentes."""
    for grupo in grupos:
        vigente = vigentes.get((grupo.turno_id, grupo.fecha)) if grupo.turno_id is not None else None
        grupo.vigente_id = vigente.id if vigente is not None else None
        if grupo.error:
            grupo.resultado, grupo.aplicar = ResultadoCarga.error, False
        elif vigente is not None and vigente.contenido_sha256 == grupo.sha:
            grupo.resultado, grupo.aplicar = ResultadoCarga.igual, False
        elif grupo.sin_riego:
            # Deducir "no se regó" de la ausencia de filas es más débil que un aplicado ya guardado.
            grupo.resultado = ResultadoCarga.sin_riego
            grupo.aplicar = vigente is None or vigente.estado != EstadoRiego.aplicado
        elif vigente is None:
            grupo.resultado, grupo.aplicar = ResultadoCarga.nuevo, True
        elif vigente.estado == EstadoRiego.provisional:
            grupo.resultado, grupo.aplicar = ResultadoCarga.reemplaza_provisional, True
        else:
            grupo.resultado = ResultadoCarga.reemplaza_aplicado
            grupo.aplicar = vigente.origen != OrigenRiego.manual


def _contadores(resultados) -> dict[str, int]:
    conteo = Counter(r.value if hasattr(r, "value") else str(r) for r in resultados)
    return {r.value: conteo.get(r.value, 0) for r in ResultadoCarga}


# --- Casos de uso --------------------------------------------------------------------

def vence_at(carga: CargaRiego) -> dt.datetime:
    return carga.subido_at + VIGENCIA


def _vencida_por_tiempo(carga: CargaRiego) -> bool:
    return carga.estado == EstadoCarga.previsualizada and ahora_utc() >= vence_at(carga)


def crear_carga(
    db: Session, *, modulo_id: int, archivo: ArchivoValidado, actor: Usuario,
    contexto: ContextoPeticion | None = None,
) -> CargaRiego:
    """Lee el archivo ya validado, arma la vista previa y la guarda (estado ``previsualizada``)."""
    modulo = db.get(Modulo, modulo_id)
    if modulo is None or not modulo.activo:
        raise NoEncontrado("No existe el módulo indicado.")
    crudos, diag = leer_hoja(archivo)
    fundo = db.get(Fundo, modulo.fundo_id)
    turnos = [t for t in repo.turnos_de_modulo(db, modulo.id) if t.activo]
    grupos, resumen = agrupar(crudos, modulo, turnos, ambiente_service.nombre_fundo(fundo), hoy_lima())
    clasificar(grupos, repo.resumen_vigentes(db, modulo.id))

    contadores = _contadores(g.resultado for g in grupos)
    fechas = [g.fecha for g in grupos]
    resumen = {
        "contadores": contadores,
        "turno_dias": len(grupos),
        "filas_leidas": int(diag.get("Riego: filas originales", len(crudos))),
        "desde": min(fechas).isoformat() if fechas else None,
        "hasta": max(fechas).isoformat() if fechas else None,
        **resumen,
    }
    carga = CargaRiego(
        modulo_id=modulo.id, archivo_nombre=archivo.nombre, sha256=archivo.sha256,
        tamano_bytes=archivo.tamano, subido_por=actor.id, subido_at=ahora_utc(),
        estado=EstadoCarga.previsualizada, resumen=resumen,
    )
    db.add(carga)
    db.flush()
    repo.insertar_grupos(db, [
        {
            "carga_id": carga.id, "fecha": g.fecha, "turno_id": g.turno_id,
            "turno_codigo": g.turno_codigo, "resultado": g.resultado,
            "vigente_id_comparado": g.vigente_id, "ciclos": g.ciclos, "mensajes": g.mensajes,
            "aplicar": g.aplicar,
        }
        for g in grupos
    ])
    auditoria_service.registrar(
        db, accion=auditoria_service.EXCEL_SUBIDO, entidad=auditoria_service.ENTIDAD_CARGA_RIEGO,
        entidad_id=carga.id, actor=actor, contexto=contexto,
        detalle={"modulo_id": modulo.id, "archivo": archivo.nombre, "sha256": archivo.sha256,
                 "tamano_bytes": archivo.tamano, "contadores": contadores,
                 "desde": resumen["desde"], "hasta": resumen["hasta"]},
    )
    db.flush()
    return carga


def _obtener(db: Session, carga_id: int, *, bloquear: bool = False) -> CargaRiego:
    carga = repo.carga(db, carga_id, bloquear=bloquear)
    if carga is None:
        raise NoEncontrado("No existe la carga indicada.")
    return carga


def obtener(db: Session, carga_id: int) -> CargaRiego:
    """La carga; si pasaron 24 h desde que se subió, queda ``vencida``."""
    carga = _obtener(db, carga_id)
    if _vencida_por_tiempo(carga):
        carga.estado = EstadoCarga.vencida
        db.flush()
    return carga


def _vencer(db: Session, carga: CargaRiego, motivo: str) -> None:
    carga.estado = EstadoCarga.vencida
    carga.resumen = {**(carga.resumen or {}), "vencida_motivo": motivo}
    db.commit()  # excepción documentada: la carga queda vencida aunque se responda 409
    raise CargaVencida()


def _exigir_previsualizada(db: Session, carga: CargaRiego) -> None:
    if carga.estado == EstadoCarga.confirmada:
        raise Conflicto("La carga ya fue confirmada.")
    if carga.estado == EstadoCarga.descartada:
        raise Conflicto("La carga fue descartada.")
    if carga.estado == EstadoCarga.vencida:
        raise CargaVencida()
    if _vencida_por_tiempo(carga):
        _vencer(db, carga, "pasaron 24 horas")


def marcar(db: Session, carga_id: int, cambios: list[tuple[int, bool]]) -> CargaRiego:
    """Marca o desmarca grupos aplicables (``igual`` y ``error`` no se pueden aplicar)."""
    carga = _obtener(db, carga_id, bloquear=True)
    _exigir_previsualizada(db, carga)
    finales = dict(cambios)  # si un id se repite, gana el último
    grupos = repo.grupos_por_id(db, carga.id, finales)
    if len(grupos) != len(finales):
        raise DatosInvalidos("Hay grupos que no pertenecen a esta carga.")
    if any(g.resultado not in RESULTADOS_APLICABLES for g in grupos.values()):
        raise DatosInvalidos("Los turno-días «igual» o con error no se pueden marcar.")
    for valor in (True, False):
        ids = [i for i, aplicar in finales.items() if aplicar is valor and grupos[i].aplicar is not valor]
        repo.fijar_aplicar(db, carga.id, ids, valor)
    db.flush()
    return carga


def confirmar(
    db: Session, carga_id: int, *, actor: Usuario, contexto: ContextoPeticion | None = None
) -> CargaRiego:
    """Aplica lo marcado (versión nueva aplicado/excel por turno-día) o vence la carga (409)."""
    carga = _obtener(db, carga_id, bloquear=True)
    _exigir_previsualizada(db, carga)
    grupos = repo.grupos_para_confirmar(db, carga.id)
    a_aplicar = [g for g in grupos if g.aplicar and g.resultado in RESULTADOS_APLICABLES]
    if not a_aplicar:
        raise DatosInvalidos("No hay turno-días marcados para aplicar.")

    comparados = [g for g in grupos if g.turno_id is not None and g.resultado != ResultadoCarga.error]
    actuales = repo.bloquear_vigentes(
        db, carga.modulo_id, min(g.fecha for g in comparados), max(g.fecha for g in comparados)
    )
    cambiados = [
        g for g in comparados
        if (actuales[(g.turno_id, g.fecha)].id if (g.turno_id, g.fecha) in actuales else None)
        != g.vigente_id_comparado
    ]
    if cambiados:
        _vencer(db, carga, f"cambió el registro vigente de {len(cambiados)} turno-días")

    versiones = repo.max_versiones(db, carga.modulo_id)
    nuevos: list[dict[str, Any]] = []
    ciclos_por_clave: dict[tuple[int, dt.date], list[dict[str, Any]]] = {}
    for g in a_aplicar:
        sin_riego = g.resultado == ResultadoCarga.sin_riego
        ciclos = [] if sin_riego else list(g.ciclos or [])
        nuevos.append({
            "modulo_id": carga.modulo_id, "turno_id": g.turno_id, "fecha": g.fecha,
            "version": versiones.get((g.turno_id, g.fecha), 0) + 1, "vigente": True,
            "estado": EstadoRiego.aplicado, "origen": OrigenRiego.excel, "sin_riego": sin_riego,
            "contenido_sha256": hash_contenido(ciclos, sin_riego), "carga_id": carga.id,
            "basado_en_id": g.vigente_id_comparado,
            "motivo": MOTIVO_SIN_RIEGO if sin_riego else MOTIVO_EXCEL, "creado_por": actor.id,
        })
        ciclos_por_clave[(g.turno_id, g.fecha)] = ciclos
    reemplazados = [g.vigente_id_comparado for g in a_aplicar if g.vigente_id_comparado is not None]
    try:
        with db.begin_nested():
            repo.dejar_de_ser_vigentes(db, reemplazados)
            ids = repo.insertar_registros(db, nuevos)
            repo.insertar_ciclos(db, [
                {"registro_id": ids[clave], **ciclo}
                for clave, ciclos in ciclos_por_clave.items() for ciclo in ciclos
            ])
    except IntegrityError:
        # Otro usuario creó una versión del mismo turno-día en paralelo.
        _vencer(db, carga, "otro usuario cambió un turno-día al mismo tiempo")

    aplicados = _contadores(g.resultado for g in a_aplicar)
    carga.estado = EstadoCarga.confirmada
    carga.confirmado_por = actor.id
    carga.confirmado_at = ahora_utc()
    carga.resumen = {**(carga.resumen or {}), "aplicados": aplicados, "registros_creados": len(nuevos)}
    fechas = [g.fecha for g in a_aplicar]
    auditoria_service.registrar(
        db, accion=auditoria_service.EXCEL_CONFIRMADO, entidad=auditoria_service.ENTIDAD_CARGA_RIEGO,
        entidad_id=carga.id, actor=actor, contexto=contexto,
        detalle={"modulo_id": carga.modulo_id, "archivo": carga.archivo_nombre, "sha256": carga.sha256,
                 "aplicados": aplicados, "registros_creados": len(nuevos),
                 "versiones_reemplazadas": len(reemplazados),
                 "desde": min(fechas).isoformat(), "hasta": max(fechas).isoformat()},
    )
    db.flush()
    return carga


def descartar(
    db: Session, carga_id: int, *, actor: Usuario, contexto: ContextoPeticion | None = None
) -> CargaRiego:
    """Descarta una carga no confirmada (vista previa o vencida). Repetirlo no cambia nada."""
    carga = _obtener(db, carga_id, bloquear=True)
    if carga.estado == EstadoCarga.confirmada:
        raise Conflicto("La carga ya fue confirmada: no se puede descartar.")
    if carga.estado == EstadoCarga.descartada:
        return carga
    estado_anterior = EstadoCarga.vencida if _vencida_por_tiempo(carga) else carga.estado
    carga.estado = EstadoCarga.descartada
    auditoria_service.registrar(
        db, accion=auditoria_service.EXCEL_DESCARTADO, entidad=auditoria_service.ENTIDAD_CARGA_RIEGO,
        entidad_id=carga.id, actor=actor, contexto=contexto,
        detalle={"modulo_id": carga.modulo_id, "archivo": carga.archivo_nombre,
                 "estado_anterior": estado_anterior.value},
    )
    db.flush()
    return carga


# --- Salida ------------------------------------------------------------------------

def _utc(instante: dt.datetime | None) -> dt.datetime | None:
    """Instantes siempre en UTC en la respuesta (recién creados o leídos de la BD, igual)."""
    return None if instante is None else instante.astimezone(dt.UTC)



def detalle(db: Session, carga: CargaRiego) -> dict[str, Any]:
    """Carga con sus grupos, lista para ``CargaRiegoSalida``."""
    nombres = repo.usernames(db, [carga.subido_por, carga.confirmado_por])
    grupos = [
        {
            "id": g.id, "fecha": g.fecha, "turno_id": g.turno_id, "turno_codigo": g.turno_codigo,
            "resultado": g.resultado, "aplicar": g.aplicar,
            "vigente_id_comparado": g.vigente_id_comparado, "vigente_estado": g.vigente_estado,
            "vigente_origen": g.vigente_origen, "ciclos": g.ciclos or [], "mensajes": g.mensajes or [],
        }
        for g in repo.grupos_de_carga(db, carga.id)
    ]
    return {
        "id": carga.id, "modulo_id": carga.modulo_id, "archivo_nombre": carga.archivo_nombre,
        "sha256": carga.sha256, "tamano_bytes": carga.tamano_bytes, "subido_at": _utc(carga.subido_at),
        "subido_por": nombres.get(carga.subido_por), "estado": carga.estado,
        "vence_at": _utc(vence_at(carga)), "confirmado_at": _utc(carga.confirmado_at),
        "confirmado_por": nombres.get(carga.confirmado_por), "resumen": carga.resumen,
        "grupos": grupos,
    }
