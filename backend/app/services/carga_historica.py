"""Carga histórica idempotente (``python -m app.cli cargar-historico``, §8).

Fuentes y rutas por defecto: las de ``ml/config/pipeline.yaml`` (las mismas con que se entrenó):

- ``meteo``   ``ml/data/raw/data_metereologica.xlsx`` -> ``meteo_lectura`` origen ``excel_historico``
  (``leer_meteo``: lecturas saneadas de 30 min).
- ``phytech`` ``ml/data/raw/data_phytech.xlsx`` (hojas ``Suelo_horario`` y ``Planta_diario``) ->
  ``phytech_suelo_horario`` y ``phytech_planta_diario``.
- ``ndvi``    ``ml/data/raw/phytech/completo`` (``NdviImages_*_area<PHYTECH_AREA_ID>.xlsx``) ->
  ``ndvi_imagen`` (imágenes del plot ``PHYTECH_PLOT_ID``).
- ``riego``   ``ml/data/raw/data_riego_historico.xlsx`` (hoja MOD5) -> ``riego_registro`` aplicado
  origen ``historico`` por turno-día con sus ``riego_ciclo``: ``leer_riego`` + ``limpiar_ciclos``
  (5 min, 2 m3/ha), como el Historial (§2.3). Solo fechas < hoy.

Idempotencia: sensores con ``ON CONFLICT`` (solo se actualiza lo que cambió); riego por turno-día
con el hash de contenido (igual -> se omite; distinto -> conflicto informado, o versión nueva con
``--reemplazar``). Al final se recalcula ``ambiente_diario`` de los días tocados. Repetir la carga
con los mismos archivos no inserta ni cambia nada.

Cada fuente queda registrada en ``ingesta_corrida`` (``fuente = historico_<fuente>``, disparo
``script``) y corre en un SAVEPOINT: si falla, se deshace solo esa fuente y la corrida queda en
``error``. El commit lo hace quien llama (la CLI).
"""

from __future__ import annotations

import datetime as dt
import glob
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from riego_ml.dataset.limpieza import limpiar_ciclos
from riego_ml.sources.meteo import leer_meteo
from riego_ml.sources.riego import leer_riego
from riego_ml.utils.tiempo import norm_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import redactar
from app.core.tiempo import ahora_utc, hoy_lima
from app.ml.historial_bd import MIN_DURACION_MIN, MIN_RIEGO_M3HA
from app.models import Fundo, IngestaCorrida, Modulo
from app.models.enums import DisparoIngesta, EstadoIngesta, EstadoRiego, OrigenMeteo, OrigenRiego
from app.repositories import datos_campo as repo
from app.repositories import riego as repo_riego
from app.repositories.datos_campo import ConteoUpsert
from app.services import ambiente_service, lecturas_service
from app.services.riego_contenido import ciclos_para_bd, hash_contenido

logger = logging.getLogger(__name__)

FUENTES = ("meteo", "phytech", "ndvi", "riego")
HOJA_RIEGO = "MOD5"
CODIGO_MODULO = "EN01-MOD5"


@dataclass
class RutasHistorico:
    meteo: Path
    phytech: Path
    ndvi: Path
    riego: Path

    @classmethod
    def por_defecto(cls) -> RutasHistorico:
        """Las rutas de ``ml/config/pipeline.yaml`` (con las que se entrenó el modelo)."""
        from riego_ml.config import load_config

        rutas = load_config().rutas
        return cls(meteo=rutas.meteo, phytech=rutas.phytech, ndvi=rutas.phytech_crudo, riego=rutas.riego)


@dataclass
class ResultadoFuente:
    fuente: str
    filas: int = 0
    nuevas: int = 0
    actualizadas: int = 0
    omitidas: int = 0
    conflictos: int = 0
    estado: str = "ok"
    mensajes: list[str] = field(default_factory=list)
    fechas: set[dt.date] = field(default_factory=set, repr=False)
    corrida_id: int | None = None

    def sumar(self, conteo: ConteoUpsert) -> None:
        self.nuevas += conteo.nuevas
        self.actualizadas += conteo.actualizadas
        self.omitidas += conteo.omitidas
        self.filas += conteo.nuevas + conteo.actualizadas + conteo.omitidas


@dataclass
class ResultadoCarga:
    fuentes: list[ResultadoFuente]
    ambiente: ambiente_service.ResultadoAmbiente

    @property
    def con_error(self) -> bool:
        return any(f.estado == "error" for f in self.fuentes)


# --- Fuentes --------------------------------------------------------------------

def cargar_meteo(db: Session, fundo: Fundo, ruta: Path, resultado: ResultadoFuente) -> None:
    lecturas, _ = leer_meteo(ruta)
    otros = sorted(set(lecturas["Fundo"].dropna()) - {ambiente_service.nombre_fundo(fundo)})
    if otros:
        resultado.mensajes.append(f"Fundos sin registrar en la BD (omitidos): {', '.join(otros)}")
    conteo, fechas = lecturas_service.guardar_meteo(
        db, fundo, lecturas, origen=OrigenMeteo.excel_historico, corrida_id=resultado.corrida_id
    )
    resultado.sumar(conteo)
    resultado.fechas |= fechas


def cargar_phytech(db: Session, fundo: Fundo, ruta: Path, resultado: ResultadoFuente) -> None:
    horario = pd.read_excel(ruta, sheet_name="Suelo_horario")
    planta = pd.read_excel(ruta, sheet_name="Planta_diario")
    conteo, fechas = lecturas_service.guardar_suelo(db, fundo, horario, corrida_id=resultado.corrida_id)
    resultado.sumar(conteo)
    resultado.fechas |= fechas
    resultado.mensajes.append(f"Suelo horario: {conteo.nuevas} nuevas, {conteo.actualizadas} "
                              f"actualizadas, {conteo.omitidas} sin cambios")
    conteo, fechas = lecturas_service.guardar_planta(db, fundo, planta, corrida_id=resultado.corrida_id)
    resultado.sumar(conteo)
    resultado.fechas |= fechas
    resultado.mensajes.append(f"Planta diario: {conteo.nuevas} nuevas, {conteo.actualizadas} "
                              f"actualizadas, {conteo.omitidas} sin cambios")


def leer_imagenes_ndvi(carpeta: Path, area_id: int) -> pd.DataFrame:
    patron = os.path.join(str(carpeta), "**", f"NdviImages_*_area{area_id}.xlsx")
    archivos = sorted(glob.glob(patron, recursive=True))
    if not archivos:
        raise FileNotFoundError(f"No hay archivos NdviImages del área {area_id} en {carpeta}")
    return pd.concat([pd.read_excel(a) for a in archivos], ignore_index=True)


def cargar_ndvi(db: Session, fundo: Fundo, carpeta: Path, resultado: ResultadoFuente) -> None:
    imagenes = leer_imagenes_ndvi(carpeta, settings.phytech_area_id)
    conteo, fechas = lecturas_service.guardar_ndvi(
        db, fundo, imagenes, area_id=settings.phytech_area_id, plot_id=settings.phytech_plot_id,
        corrida_id=resultado.corrida_id,
    )
    resultado.sumar(conteo)
    resultado.fechas |= fechas


def cargar_riego(
    db: Session, modulo: Modulo, ciclos_crudos: pd.DataFrame, resultado: ResultadoFuente, *,
    reemplazar: bool = False,
) -> None:
    """``ciclos_crudos``: salida de ``leer_riego`` (sin limpiar)."""
    fundo = db.get(Fundo, modulo.fundo_id)
    turnos = {t.codigo.upper(): t for t in repo_riego.turnos_de_modulo(db, modulo.id)}
    ciclos, descartados, _ = limpiar_ciclos(ciclos_crudos, MIN_DURACION_MIN, MIN_RIEGO_M3HA)
    resultado.mensajes.append(
        f"{len(ciclos_crudos)} filas leídas, {len(descartados)} ciclos descartados por limpiar_ciclos "
        "(aperturas fallidas y duplicados)"
    )
    texto_fundo = ambiente_service.nombre_fundo(fundo)
    texto_modulo = str(norm_text(pd.Series([modulo.codigo])).iloc[0])
    propios = (ciclos["Fundo"] == texto_fundo) & (ciclos["Modulo"] == texto_modulo)
    if (~propios).any():
        resultado.mensajes.append(f"{int((~propios).sum())} ciclos de otro fundo o módulo (omitidos)")
    ciclos = ciclos[propios]
    hoy = pd.Timestamp(hoy_lima())
    futuros = ciclos["Fecha"] >= hoy
    if futuros.any():
        resultado.mensajes.append(f"{int(futuros.sum())} ciclos con fecha de hoy o posterior (omitidos)")
    ciclos = ciclos[~futuros]
    desconocidos = sorted(set(ciclos["Turno"].dropna()) - set(turnos))
    if desconocidos:
        resultado.mensajes.append(f"Turnos desconocidos (omitidos): {', '.join(desconocidos)}")
        ciclos = ciclos[ciclos["Turno"].isin(turnos)]
    dias_solo_fallidas = (
        descartados.drop_duplicates(["Fecha", "Turno"]).merge(
            ciclos[["Fecha", "Turno"]].drop_duplicates(), how="left", indicator=True)
    )
    sin_ciclos = int((dias_solo_fallidas["_merge"] == "left_only").sum())
    if sin_ciclos:
        resultado.mensajes.append(
            f"{sin_ciclos} turno-días solo con aperturas fallidas o duplicados: sin registro"
        )

    vigentes = repo_riego.resumen_vigentes(db, modulo.id)
    versiones = repo_riego.max_versiones(db, modulo.id)
    nuevos: list[dict] = []
    ciclos_por_clave: dict[tuple[int, dt.date], list[dict]] = {}
    reemplazados: list[int] = []
    grupos: dict[tuple[dt.date, str], list[dict]] = {}
    for registro in ciclos.to_dict("records"):
        clave = (pd.Timestamp(registro["Fecha"]).date(), str(registro["Turno"]))
        grupos.setdefault(clave, []).append(registro)
    for (dia, codigo), grupo in sorted(grupos.items()):
        turno = turnos[codigo]
        filas_ciclo = ciclos_para_bd(grupo)
        sha = hash_contenido(filas_ciclo)
        resultado.filas += 1
        resultado.fechas.add(dia)
        vigente = vigentes.get((turno.id, dia))
        if vigente is not None and vigente.contenido_sha256 == sha:
            resultado.omitidas += 1
            continue
        if vigente is not None and not reemplazar:
            resultado.conflictos += 1
            continue
        if vigente is not None:
            reemplazados.append(vigente.id)
        nuevos.append({
            "modulo_id": modulo.id, "turno_id": turno.id, "fecha": dia,
            "version": versiones.get((turno.id, dia), 0) + 1, "vigente": True,
            "estado": EstadoRiego.aplicado, "origen": OrigenRiego.historico, "sin_riego": False,
            "contenido_sha256": sha, "basado_en_id": vigente.id if vigente is not None else None,
            "motivo": "Carga histórica" if vigente is None else "Carga histórica (--reemplazar)",
        })
        ciclos_por_clave[(turno.id, dia)] = filas_ciclo
    if reemplazados:
        repo_riego.dejar_de_ser_vigentes(db, reemplazados)
    ids = repo_riego.insertar_registros(db, nuevos)
    repo_riego.insertar_ciclos(db, [
        {"registro_id": ids[clave], **ciclo}
        for clave, filas_ciclo in ciclos_por_clave.items() for ciclo in filas_ciclo
    ])
    resultado.nuevas += len(nuevos) - len(reemplazados)
    resultado.actualizadas += len(reemplazados)
    if resultado.conflictos:
        resultado.mensajes.append(
            f"{resultado.conflictos} turno-días con contenido distinto al vigente (sin cambios; "
            "usa --reemplazar para crear una versión nueva)"
        )


# --- Orquestación ---------------------------------------------------------------

def _con_corrida(
    db: Session, fuente: str, funcion: Callable[[ResultadoFuente], None]
) -> ResultadoFuente:
    inicio = time.monotonic()
    corrida = repo.nueva_corrida(
        db, fuente=f"historico_{fuente}", disparo=DisparoIngesta.script, inicio_at=ahora_utc(),
        estado=EstadoIngesta.en_curso,
    )
    resultado = ResultadoFuente(fuente=fuente, corrida_id=corrida.id)
    try:
        with db.begin_nested():
            funcion(resultado)
    except Exception as error:  # noqa: BLE001 - una fuente con error no detiene las demás
        logger.exception("Carga histórica: error en la fuente %s", fuente)
        resultado = ResultadoFuente(fuente=fuente, corrida_id=corrida.id, estado="error",
                                    mensajes=[redactar(f"{type(error).__name__}: {error}")[:500]])
    _cerrar_corrida(corrida, resultado, inicio)
    db.flush()
    return resultado


def _cerrar_corrida(corrida: IngestaCorrida, resultado: ResultadoFuente, inicio: float) -> None:
    if resultado.estado == "error":
        corrida.estado = EstadoIngesta.error
        corrida.errores = [{"tipo": "carga_historica", "mensaje": m} for m in resultado.mensajes]
    else:
        corrida.estado = EstadoIngesta.parcial if resultado.conflictos else EstadoIngesta.ok
        resultado.estado = corrida.estado.value
    corrida.fin_at = ahora_utc()
    corrida.duracion_ms = int((time.monotonic() - inicio) * 1000)
    corrida.filas_nuevas = resultado.nuevas
    corrida.filas_actualizadas = resultado.actualizadas
    corrida.filas_omitidas = resultado.omitidas
    corrida.conflictos = resultado.conflictos
    if resultado.fechas:
        corrida.desde, corrida.hasta = min(resultado.fechas), max(resultado.fechas)


def cargar_historico(
    db: Session,
    rutas: RutasHistorico | None = None,
    *,
    fuentes: tuple[str, ...] = FUENTES,
    reemplazar: bool = False,
    codigo_modulo: str = CODIGO_MODULO,
) -> ResultadoCarga:
    """Carga las ``fuentes`` y recalcula ``ambiente_diario`` de los días tocados."""
    rutas = rutas or RutasHistorico.por_defecto()
    modulo = repo.modulo_por_codigo(db, codigo_modulo)
    if modulo is None:
        raise ValueError(f"No existe el módulo {codigo_modulo}: corre primero las migraciones (semillas).")
    fundo = db.get(Fundo, modulo.fundo_id)

    tareas: dict[str, Callable[[ResultadoFuente], None]] = {
        "meteo": lambda r: cargar_meteo(db, fundo, rutas.meteo, r),
        "phytech": lambda r: cargar_phytech(db, fundo, rutas.phytech, r),
        "ndvi": lambda r: cargar_ndvi(db, fundo, rutas.ndvi, r),
        "riego": lambda r: cargar_riego(db, modulo, leer_riego(rutas.riego, HOJA_RIEGO)[0], r,
                                        reemplazar=reemplazar),
    }
    resultados = [_con_corrida(db, fuente, tareas[fuente]) for fuente in FUENTES if fuente in fuentes]

    fechas_ambiente: set[dt.date] = set()
    for resultado in resultados:
        if resultado.fuente != "riego":
            fechas_ambiente |= resultado.fechas
    ambiente = ambiente_service.recalcular(db, fundo, fechas_ambiente)
    db.flush()
    return ResultadoCarga(resultados, ambiente)
