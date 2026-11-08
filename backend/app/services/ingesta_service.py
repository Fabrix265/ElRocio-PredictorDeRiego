"""Ingesta de las APIs (§3.6): WeatherLink, Phytech suelo, Phytech planta, NDVI y pronóstico.

Cada fuente es una corrida en ``ingesta_corrida`` y cada llamada a la API deja su payload tal cual
en ``ingesta_crudo`` (con los parámetros de negocio, nunca las claves). Después se guardan las
lecturas limpias (``lecturas_service``) y se recalcula ``ambiente_diario`` de los días tocados.

Rango por defecto de cada fuente (``rango_automatico``): desde la última fecha guardada menos
:data:`SOLAPE_DIAS` (refresco, como los scripts de descarga) hasta ayer (hora de Lima); si en los
últimos :data:`VENTANA_HUECOS_DIAS` días hay un día sin dato anterior a eso, se empieza en ese
hueco, así los huecos recientes se corrigen solos. Si la fuente está vacía se piden los últimos
:data:`DIAS_SIN_HISTORIA` días, y nunca más de :data:`MAX_DIAS_AUTOMATICO` (los huecos más viejos
se cargan a mano con ``python -m app.cli ingestar --desde --hasta``). NDVI: los últimos 10 días.
Pronóstico: una captura por día (fecha de captura = hoy).

Reglas:

- WeatherLink nunca pisa una lectura del Excel histórico (``repositories.datos_campo.upsert_meteo``)
  y convierte las unidades con ``app.integraciones.weatherlink.conversion`` (°C, mm y km, las del
  entrenamiento).
- Un error en una llamada no detiene las demás llamadas de la fuente (corrida ``parcial``) y un
  error en una fuente no detiene las demás fuentes (cada fuente corre en un SAVEPOINT y, fuera de la
  API, en su propia transacción: ver :func:`ejecutar_en_sesiones`).
- Transacciones: las funciones hacen ``flush``; el commit lo hace quien llama.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import Conflicto, DatosInvalidos
from app.core.logging import redactar
from app.core.tiempo import ahora_utc, hoy_lima
from app.db.session import unidad_de_trabajo
from app.integraciones.http import ErrorIntegracion, Llamada, TipoError
from app.integraciones.phytech import adaptador as phytech_adaptador
from app.integraciones.phytech.cliente import DIAS_NDVI, DIAS_PLANTA, DIAS_SUELO, ClientePhytech, tramos
from app.integraciones.weatherlink import conversion
from app.integraciones.weatherlink.cliente import ClienteWeatherLink
from app.ml.columnas import PLANTA_MEDICIONES
from app.models import Fundo, IngestaCorrida
from app.models.enums import DisparoIngesta, EstadoIngesta, OrigenMeteo
from app.repositories import datos_campo as repo_datos
from app.repositories import ingestas as repo
from app.repositories.datos_campo import ConteoUpsert
from app.services import ambiente_service, auditoria_service, lecturas_service

logger = logging.getLogger(__name__)

WEATHERLINK = "weatherlink"
PHYTECH_SUELO = "phytech_suelo"
PHYTECH_PLANTA = "phytech_planta"
NDVI = "ndvi"
PRONOSTICO = "pronostico"
FUENTES: tuple[str, ...] = (WEATHERLINK, PHYTECH_SUELO, PHYTECH_PLANTA, NDVI, PRONOSTICO)
FUENTE_REPROCESAR = "reprocesar_weatherlink"

SOLAPE_DIAS = 3
DIAS_SIN_HISTORIA = 7
VENTANA_HUECOS_DIAS = 14
MIN_LECTURAS_DIA = 36  # como meteo_diaria: con menos, el día queda sin clima
MAX_DIAS_AUTOMATICO = 62
MAX_DIAS_MANUAL = 62  # "Actualizar ahora" con rango (la CLI no tiene tope)
LATIDO_SEGUNDOS = 60  # cada cuánto el proceso que ejecuta una corrida actualiza latido_at
MINUTOS_SIN_LATIDO = 10  # sin latido en ese tiempo, la corrida en curso no tiene dueño
CODIGO_MODULO_DATOS = "EN01-MOD5"  # los sensores (IDs del .env) se asocian a su fundo (§2.2)


# --- Clientes -------------------------------------------------------------------

class Clientes:
    """Crea los clientes HTTP al primer uso y los reutiliza en toda la ingesta (el token de
    Phytech se pide una vez). Si faltan las claves, la fuente termina en error de configuración."""

    def __init__(
        self,
        weatherlink: Callable[[], ClienteWeatherLink] | None = None,
        phytech: Callable[[], ClientePhytech] | None = None,
    ) -> None:
        self._fabricas = {WEATHERLINK: weatherlink or _weatherlink_desde_config,
                          "phytech": phytech or _phytech_desde_config}
        self._creados: dict[str, Any] = {}

    def _obtener(self, nombre: str) -> Any:
        if nombre not in self._creados:
            self._creados[nombre] = self._fabricas[nombre]()
        return self._creados[nombre]

    def weatherlink(self) -> ClienteWeatherLink:
        return self._obtener(WEATHERLINK)

    def phytech(self) -> ClientePhytech:
        return self._obtener("phytech")

    def cerrar(self) -> None:
        for cliente in self._creados.values():
            cliente.cerrar()
        self._creados.clear()


def _weatherlink_desde_config() -> ClienteWeatherLink:
    return ClienteWeatherLink(
        api_key=settings.weatherlink_api_key.get_secret_value(),
        api_secret=settings.weatherlink_api_secret.get_secret_value(),
        base_url=settings.weatherlink_api_base_url, station_id=settings.weatherlink_station_id,
    )


def _phytech_desde_config() -> ClientePhytech:
    return ClientePhytech(
        api_key=settings.phytech_api_key.get_secret_value(),
        api_secret=settings.phytech_api_secret.get_secret_value(),
        base_url=settings.phytech_api_base_url,
    )


# --- Resultado de una fuente ----------------------------------------------------

@dataclass
class ResultadoFuente:
    conteo: ConteoUpsert = field(default_factory=ConteoUpsert)
    fechas: set[dt.date] = field(default_factory=set)  # días a recalcular en ambiente_diario
    errores: list[dict[str, Any]] = field(default_factory=list)
    llamadas_ok: int = 0
    llamadas_error: int = 0

    def error(self, error: ErrorIntegracion) -> None:
        self.llamadas_error += 1
        self.errores.append(error.como_dict())

    @property
    def estado(self) -> EstadoIngesta:
        if not self.errores:
            return EstadoIngesta.ok
        return EstadoIngesta.parcial if self.llamadas_ok else EstadoIngesta.error


def _llamar(
    db: Session, corrida: IngestaCorrida, resultado: ResultadoFuente, funcion: Callable[[], Llamada]
) -> Llamada | None:
    """Hace una llamada, guarda su crudo y registra el error si falla (sin detener la fuente)."""
    try:
        llamada = funcion()
    except ErrorIntegracion as error:
        logger.warning("Ingesta %s: %s %s (%s)", corrida.fuente, error.tipo, error.endpoint or "",
                       error.status_code)
        resultado.error(error)
        return None
    repo.guardar_crudo(db, corrida.id, llamada.endpoint, llamada.parametros, llamada.payload)
    resultado.llamadas_ok += 1
    return llamada


def _credenciales_fallaron(resultado: ResultadoFuente) -> bool:
    return any(e.get("tipo") in (TipoError.CREDENCIALES, TipoError.CONFIGURACION) for e in resultado.errores)


def _dias(desde: dt.date, hasta: dt.date) -> list[dt.date]:
    return [desde + dt.timedelta(days=i) for i in range((hasta - desde).days + 1)]


# --- Fuentes --------------------------------------------------------------------

@dataclass
class Contexto:
    db: Session
    corrida: IngestaCorrida
    fundo: Fundo
    clientes: Clientes
    desde: dt.date
    hasta: dt.date
    hoy: dt.date

    @property
    def texto_fundo(self) -> str:
        return ambiente_service.nombre_fundo(self.fundo)


def ingestar_weatherlink(ctx: Contexto) -> ResultadoFuente:
    resultado = ResultadoFuente()
    try:
        cliente = ctx.clientes.weatherlink()
    except ErrorIntegracion as error:
        resultado.error(error)
        return resultado
    registros: list[dict[str, Any]] = []
    for dia in _dias(ctx.desde, ctx.hasta):
        llamada = _llamar(ctx.db, ctx.corrida, resultado, lambda d=dia: cliente.historico_dia(d))
        if llamada is not None:
            registros.extend(registros_del_dia(llamada.payload, dia))
        if _credenciales_fallaron(resultado):
            break
    if registros:
        guardar_lecturas_weatherlink(ctx.db, ctx.fundo, registros, ctx.corrida.id, resultado)
    return resultado


def registros_del_dia(payload: dict[str, Any], dia: dt.date) -> list[dict[str, Any]]:
    """Registros del payload que pertenecen a ``dia`` con el corte de día de ``conversion``
    (``ts`` en ``(D 00:00, D+1 00:00]``); si la API devolviera alguno de otro día, se descarta."""
    return [r for r in conversion.registros_de_payload(payload) if conversion.dia_de_registro(r) == dia]


def guardar_lecturas_weatherlink(
    db: Session, fundo: Fundo, registros: list[dict[str, Any]], corrida_id: int, resultado: ResultadoFuente,
    *, pisar_excel: bool = False,
) -> None:
    """Conversión a °C/mm/km + ``sanear_meteo`` y guardado (sin pisar el Excel histórico, salvo
    ``pisar_excel``)."""
    lecturas, _ = conversion.lecturas_saneadas(registros, ambiente_service.nombre_fundo(fundo))
    conteo, fechas = lecturas_service.guardar_meteo(
        db, fundo, lecturas, origen=OrigenMeteo.weatherlink, corrida_id=corrida_id,
        pisar_excel=pisar_excel,
    )
    resultado.conteo = resultado.conteo.sumar(conteo)
    resultado.fechas |= fechas


def ingestar_phytech_suelo(ctx: Contexto) -> ResultadoFuente:
    resultado = ResultadoFuente()
    try:
        cliente = ctx.clientes.phytech()
    except ErrorIntegracion as error:
        resultado.error(error)
        return resultado
    payloads = []
    for inicio, fin in tramos(ctx.desde, ctx.hasta, DIAS_SUELO):
        llamada = _llamar(ctx.db, ctx.corrida, resultado,
                          lambda i=inicio, f=fin: cliente.suelo_horario(settings.phytech_area_id, i, f))
        if llamada is not None:
            payloads.append(llamada.payload)
        if _credenciales_fallaron(resultado):
            break
    horario, _ = phytech_adaptador.suelo_horario(payloads, settings.phytech_plot_id, ctx.texto_fundo)
    if not horario.empty:
        conteo, fechas = lecturas_service.guardar_suelo(
            ctx.db, ctx.fundo, horario, corrida_id=ctx.corrida.id, proteger_con_dato=True
        )
        resultado.conteo = resultado.conteo.sumar(conteo)
        resultado.fechas |= fechas
    return resultado


COLUMNAS_PLANTA_API = (*PLANTA_MEDICIONES, "et_mm", "lluvia_mm")


def ingestar_phytech_planta(ctx: Contexto) -> ResultadoFuente:
    resultado = ResultadoFuente()
    try:
        cliente = ctx.clientes.phytech()
    except ErrorIntegracion as error:
        resultado.error(error)
        return resultado
    payloads = []
    for inicio, fin in tramos(ctx.desde, ctx.hasta, DIAS_PLANTA):
        llamada = _llamar(ctx.db, ctx.corrida, resultado,
                          lambda i=inicio, f=fin: cliente.planta_diaria(settings.phytech_area_id, i, f))
        if llamada is not None:
            payloads.append(llamada.payload)
        if _credenciales_fallaron(resultado):
            break
    planta = phytech_adaptador.planta_diario(payloads, settings.phytech_plot_id, ctx.texto_fundo)
    if not planta.empty:
        conteo, fechas = lecturas_service.guardar_planta(
            ctx.db, ctx.fundo, planta, corrida_id=ctx.corrida.id, columnas=COLUMNAS_PLANTA_API
        )
        resultado.conteo = resultado.conteo.sumar(conteo)
        resultado.fechas |= fechas
    return resultado


def ingestar_ndvi(ctx: Contexto) -> ResultadoFuente:
    resultado = ResultadoFuente()
    try:
        cliente = ctx.clientes.phytech()
    except ErrorIntegracion as error:
        resultado.error(error)
        return resultado
    payloads = []
    for inicio, fin in tramos(ctx.desde, ctx.hasta, DIAS_NDVI):
        llamada = _llamar(ctx.db, ctx.corrida, resultado,
                          lambda i=inicio, f=fin: cliente.ndvi(settings.phytech_area_id, i, f))
        if llamada is not None:
            payloads.append(llamada.payload)
        if _credenciales_fallaron(resultado):
            break
    imagenes = phytech_adaptador.imagenes_ndvi(payloads)
    if not imagenes.empty:
        conteo, fechas = lecturas_service.guardar_ndvi(
            ctx.db, ctx.fundo, imagenes, area_id=settings.phytech_area_id,
            plot_id=settings.phytech_plot_id, corrida_id=ctx.corrida.id,
        )
        resultado.conteo = resultado.conteo.sumar(conteo)
        resultado.fechas |= fechas
    return resultado


def ingestar_pronostico(ctx: Contexto) -> ResultadoFuente:
    resultado = ResultadoFuente()
    try:
        cliente = ctx.clientes.phytech()
    except ErrorIntegracion as error:
        resultado.error(error)
        return resultado
    llamada = _llamar(ctx.db, ctx.corrida, resultado, lambda: cliente.pronostico(settings.phytech_area_id))
    if llamada is None:
        return resultado
    tabla = phytech_adaptador.pronostico(llamada.payload, settings.phytech_plot_id)
    filas = [
        {"fundo_id": ctx.fundo.id, "project_id": int(f["project_id"]), "capturado_fecha": ctx.hoy,
         "fecha": f["fecha"], "corrida_id": ctx.corrida.id,
         **{c: None if pd.isna(f[c]) else float(f[c]) for c in repo.COLUMNAS_PRONOSTICO}}
        for f in tabla.to_dict("records")
    ]
    resultado.conteo = resultado.conteo.sumar(repo.upsert_pronostico(ctx.db, filas))
    return resultado  # el pronóstico no entra en ambiente_diario


INGESTORES: dict[str, Callable[[Contexto], ResultadoFuente]] = {
    WEATHERLINK: ingestar_weatherlink,
    PHYTECH_SUELO: ingestar_phytech_suelo,
    PHYTECH_PLANTA: ingestar_phytech_planta,
    NDVI: ingestar_ndvi,
    PRONOSTICO: ingestar_pronostico,
}


# --- Rangos ---------------------------------------------------------------------

def fundo_de_datos(db: Session) -> Fundo:
    modulo = repo_datos.modulo_por_codigo(db, CODIGO_MODULO_DATOS)
    if modulo is None:
        raise ValueError(f"No existe el módulo {CODIGO_MODULO_DATOS}: corre primero las migraciones.")
    return repo_datos.fundo_por_id(db, modulo.fundo_id)


def ultima_fecha(db: Session, fuente: str, fundo: Fundo) -> dt.date | None:
    if fuente == WEATHERLINK:
        return repo.ultima_meteo(db, fundo.id)
    if fuente == PHYTECH_SUELO:
        return repo.ultima_suelo(db, settings.phytech_project_id)
    if fuente == PHYTECH_PLANTA:
        return repo.ultima_planta(db, settings.phytech_project_id)
    if fuente == NDVI:
        return repo.ultima_ndvi(db, fundo.id, settings.phytech_plot_id)
    return repo.ultima_captura_pronostico(db, settings.phytech_project_id)


def dias_con_dato(db: Session, fuente: str, fundo: Fundo, desde: dt.date, hasta: dt.date) -> set[dt.date]:
    if fuente == WEATHERLINK:
        return repo.dias_meteo(db, fundo.id, desde, hasta, MIN_LECTURAS_DIA)
    if fuente == PHYTECH_SUELO:
        return repo.dias_suelo(db, settings.phytech_project_id, desde, hasta)
    if fuente == PHYTECH_PLANTA:
        return repo.dias_planta(db, settings.phytech_project_id, desde, hasta)
    raise ValueError(f"Fuente sin detección de huecos: {fuente}")


def rango_automatico(db: Session, fuente: str, fundo: Fundo, hoy: dt.date) -> tuple[dt.date, dt.date]:
    """Rango de la ingesta programada o de "Actualizar ahora" sin fechas (``hoy`` en hora de Lima).

    WeatherLink y Phytech: desde la última fecha guardada − :data:`SOLAPE_DIAS` (o desde el primer
    hueco de los últimos :data:`VENTANA_HUECOS_DIAS` días, si es anterior) hasta ayer."""
    ayer = hoy - dt.timedelta(days=1)
    if fuente == PRONOSTICO:
        return hoy, hoy
    if fuente == NDVI:
        return ayer - dt.timedelta(days=DIAS_NDVI - 1), ayer
    ultima = ultima_fecha(db, fuente, fundo)
    if ultima is None:
        return ayer - dt.timedelta(days=DIAS_SIN_HISTORIA - 1), ayer
    desde = ultima - dt.timedelta(days=SOLAPE_DIAS)
    inicio_ventana = ayer - dt.timedelta(days=VENTANA_HUECOS_DIAS - 1)
    con_dato = dias_con_dato(db, fuente, fundo, inicio_ventana, min(ultima, ayer))
    huecos = [d for d in _dias(inicio_ventana, min(ultima, ayer)) if d not in con_dato]
    if huecos:
        desde = min(desde, huecos[0])
    desde = max(desde, ayer - dt.timedelta(days=MAX_DIAS_AUTOMATICO - 1))
    return min(desde, ayer), ayer


# --- Corridas -------------------------------------------------------------------

def validar_fuentes(fuentes: Iterable[str] | None) -> tuple[str, ...]:
    pedidas = tuple(dict.fromkeys(fuentes or FUENTES))
    desconocidas = [f for f in pedidas if f not in FUENTES]
    if desconocidas:
        raise ValueError(f"Fuentes desconocidas: {', '.join(desconocidas)} (válidas: {', '.join(FUENTES)})")
    return pedidas


def crear_corridas(
    db: Session, fuentes: Sequence[str], *, disparo: DisparoIngesta, usuario_id: int | None = None,
    desde: dt.date | None = None, hasta: dt.date | None = None,
) -> list[IngestaCorrida]:
    """Corridas ``en_curso`` (manuales o de script). Sin ``desde``/``hasta`` cada fuente usa su
    rango automático, que se fija al ejecutar. ``Conflicto`` si alguna fuente ya tiene una corrida
    en curso, también si la creó otra sesión a la vez (índice único parcial
    ``uq_ingesta_corrida_en_curso``; la sesión sigue usable)."""
    pedidas = validar_fuentes(fuentes)
    ocupadas = sorted({c.fuente for c in repo.en_curso(db, pedidas)})
    if ocupadas:
        raise Conflicto(f"Ya hay una ingesta en curso de: {', '.join(ocupadas)}")
    corridas = []
    try:
        with db.begin_nested():
            for fuente in pedidas:
                ahora = ahora_utc()
                corrida = repo_datos.nueva_corrida(
                    db, fuente=fuente, disparo=disparo, usuario_id=usuario_id, inicio_at=ahora,
                    latido_at=ahora, estado=EstadoIngesta.en_curso,
                    # El pronóstico no tiene rango: siempre es la captura de hoy.
                    desde=None if fuente == PRONOSTICO else desde,
                    hasta=None if fuente == PRONOSTICO else hasta,
                )
                corridas.append(corrida)
    except IntegrityError:
        en_carrera = sorted({c.fuente for c in repo.en_curso(db, pedidas)}) or list(pedidas)
        raise Conflicto(f"Ya hay una ingesta en curso de: {', '.join(en_carrera)}") from None
    return corridas


def validar_rango(desde: dt.date | None, hasta: dt.date | None, hoy: dt.date, *,
                  maximo: int | None = None) -> tuple[dt.date | None, dt.date | None]:
    """Rango pedido a mano. Sin fechas: ``(None, None)`` (rango automático de cada fuente). Con
    solo ``hasta`` se pide ese día; con solo ``desde``, hasta ayer. Debe cumplir
    ``desde <= hasta < hoy`` y, si hay ``maximo``, no superar esa cantidad de días."""
    if desde is None and hasta is None:
        return None, None
    hasta = hasta or hoy - dt.timedelta(days=1)
    desde = desde or hasta
    if desde > hasta or hasta >= hoy:
        raise ValueError("El rango debe cumplir desde <= hasta < hoy (hora de Lima)")
    if maximo is not None and (hasta - desde).days + 1 > maximo:
        raise ValueError(f"El rango no puede superar {maximo} días")
    return desde, hasta


def lanzar_manual(
    db: Session, fuentes: Iterable[str] | None, *, usuario_id: int,
    desde: dt.date | None = None, hasta: dt.date | None = None,
) -> list[IngestaCorrida]:
    """"Actualizar ahora": valida, crea las corridas ``en_curso`` (disparo ``manual``) y las
    devuelve; quien llama confirma la transacción y las ejecuta en segundo plano
    (:func:`ejecutar_en_segundo_plano`). ``Conflicto`` si alguna fuente ya tiene una corrida en curso."""
    try:
        pedidas = validar_fuentes(fuentes)
        desde, hasta = validar_rango(desde, hasta, hoy_lima(), maximo=MAX_DIAS_MANUAL)
    except ValueError as error:
        raise DatosInvalidos(str(error)) from None
    cerrar_colgadas(db)
    return crear_corridas(db, pedidas, disparo=DisparoIngesta.manual, usuario_id=usuario_id,
                          desde=desde, hasta=hasta)


def reclamar_programadas(
    db: Session, fecha: dt.date, fuentes: Sequence[str] = FUENTES, *, solo_interrumpidas: bool = False
) -> list[int]:
    """Ids de las corridas programadas de ``fecha`` que este proceso reclamó (las que otro proceso
    ya creó y las fuentes con otra corrida en curso se omiten)."""
    ids = []
    for fuente in fuentes:
        corrida_id = repo.reclamar_programada(db, fuente, fecha, ahora_utc(),
                                              solo_interrumpida=solo_interrumpidas)
        if corrida_id is not None:
            ids.append(corrida_id)
    return ids


def ejecutar_corrida(db: Session, corrida: IngestaCorrida, clientes: Clientes) -> IngestaCorrida:
    """Ejecuta una corrida ``en_curso``: descarga, guarda, recalcula ``ambiente_diario`` y la
    cierra con su estado. Nunca lanza por un error de la API (queda en ``corrida.errores``)."""
    inicio = time.monotonic()
    hoy = hoy_lima()
    resultado = ResultadoFuente()
    try:
        fundo = fundo_de_datos(db)
        if corrida.desde is None or corrida.hasta is None:
            corrida.desde, corrida.hasta = rango_automatico(db, corrida.fuente, fundo, hoy)
        ctx = Contexto(db, corrida, fundo, clientes, corrida.desde, corrida.hasta, hoy)
        with db.begin_nested():
            resultado = INGESTORES[corrida.fuente](ctx)
            if resultado.fechas:
                ambiente_service.recalcular(db, fundo, resultado.fechas)
    except Exception as error:  # noqa: BLE001 - una fuente con error no detiene las demás
        logger.exception("Ingesta %s: error inesperado", corrida.fuente)
        resultado = ResultadoFuente(errores=[*resultado.errores, {
            "tipo": TipoError.INTERNO, "status_code": None, "endpoint": None,
            "mensaje": redactar(f"{type(error).__name__}: {error}")[:300],
        }])
    corrida.estado = resultado.estado
    corrida.errores = resultado.errores
    corrida.filas_nuevas = resultado.conteo.nuevas
    corrida.filas_actualizadas = resultado.conteo.actualizadas
    corrida.filas_omitidas = resultado.conteo.omitidas
    corrida.fin_at = ahora_utc()
    corrida.duracion_ms = int((time.monotonic() - inicio) * 1000)
    db.flush()
    logger.info("Ingesta %s (%s a %s): %s, %s nuevas, %s actualizadas, %s sin cambios",
                corrida.fuente, corrida.desde, corrida.hasta, corrida.estado.value,
                corrida.filas_nuevas, corrida.filas_actualizadas, corrida.filas_omitidas)
    return corrida


class Latido:
    """Hilo que actualiza ``latido_at`` de una corrida cada ``cada`` segundos, en transacciones
    cortas propias (la de la ingesta no se confirma hasta el final y no toca la fila de la corrida
    hasta cerrarla). Si el proceso muere, el latido se detiene y :func:`cerrar_colgadas` la cierra
    en :data:`MINUTOS_SIN_LATIDO` minutos."""

    def __init__(self, corrida_id: int, *, cada: float = LATIDO_SEGUNDOS,
                 sesion: Callable[[], Any] = unidad_de_trabajo) -> None:
        self.corrida_id = corrida_id
        self.cada = cada
        self._sesion = sesion
        self._parar = threading.Event()
        self._hilo = threading.Thread(target=self._latir, name=f"latido-ingesta-{corrida_id}", daemon=True)
        self.latidos = 0

    def _latir(self) -> None:
        while not self._parar.wait(self.cada):
            try:
                with self._sesion() as db:
                    if repo.marcar_latido(db, self.corrida_id, ahora_utc()):
                        self.latidos += 1
            except Exception:  # noqa: BLE001 - un latido perdido no detiene la ingesta
                logger.warning("Ingesta: no se pudo registrar el latido de la corrida %s", self.corrida_id)

    def __enter__(self) -> Latido:
        self._hilo.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self._parar.set()  # sin join: un latido en espera de candado no demora la ingesta


@contextmanager
def _sin_latido(_corrida_id: int):
    yield None


def preparar_corrida(db: Session, corrida: IngestaCorrida) -> None:
    """Fija el rango automático y el latido antes de ejecutar, en una transacción corta: así la
    transacción de la ingesta no modifica la fila de la corrida hasta cerrarla y el latido (otra
    conexión) no espera su candado. Si falla, :func:`ejecutar_corrida` lo repite y registra el error."""
    corrida.latido_at = ahora_utc()
    if corrida.desde is None or corrida.hasta is None:
        try:
            corrida.desde, corrida.hasta = rango_automatico(db, corrida.fuente, fundo_de_datos(db), hoy_lima())
        except Exception:  # noqa: BLE001
            logger.exception("Ingesta %s: no se pudo calcular el rango", corrida.fuente)
    db.flush()


def _marcar_no_guardada(corrida_id: int, sesion: Callable[[], Any], error: Exception) -> None:
    """La ingesta no se pudo confirmar (p. ej. la BD cayó): se intenta cerrar la corrida como error
    en otra transacción, para no dejarla en curso hasta que venza su latido."""
    try:
        with sesion() as db:
            corrida = db.get(IngestaCorrida, corrida_id)
            if corrida is not None and corrida.estado == EstadoIngesta.en_curso:
                corrida.estado = EstadoIngesta.error
                corrida.fin_at = ahora_utc()
                corrida.errores = [{"tipo": TipoError.INTERNO, "status_code": None, "endpoint": None,
                                    "mensaje": redactar(f"No se pudo guardar: {type(error).__name__}")[:300]}]
    except Exception:  # noqa: BLE001 - quedará en curso hasta que venza el latido
        logger.exception("Ingesta: tampoco se pudo cerrar la corrida %s", corrida_id)


def ejecutar_en_sesiones(
    corrida_ids: Sequence[int], clientes: Clientes | None = None,
    sesion: Callable[[], Any] = unidad_de_trabajo, *, latido: float | None = LATIDO_SEGUNDOS,
) -> list[IngestaCorrida]:
    """Ejecuta cada corrida en su propia transacción (commit por fuente), con un :class:`Latido`
    mientras corre (``latido=None`` lo desactiva): lo que usan la tarea programada, "Actualizar
    ahora" (en segundo plano) y la CLI."""
    propios = clientes is None
    clientes = clientes or Clientes()
    corridas = []
    try:
        for corrida_id in corrida_ids:
            try:
                with sesion() as db:
                    corrida = db.get(IngestaCorrida, corrida_id)
                    if corrida is None or corrida.estado != EstadoIngesta.en_curso:
                        continue
                    preparar_corrida(db, corrida)
                vigilancia = (Latido(corrida_id, cada=latido, sesion=sesion) if latido
                              else _sin_latido(corrida_id))
                with vigilancia, sesion() as db:
                    corrida = db.get(IngestaCorrida, corrida_id)
                    if corrida is None or corrida.estado != EstadoIngesta.en_curso:
                        continue  # otro proceso la cerró por falta de latido
                    terminada = ejecutar_corrida(db, corrida, clientes)
                corridas.append(terminada)  # solo si se confirmó
            except Exception as error:  # noqa: BLE001 - p. ej. la BD cayó al confirmar: siguiente fuente
                logger.exception("Ingesta: no se pudo guardar la corrida %s", corrida_id)
                _marcar_no_guardada(corrida_id, sesion, error)
    finally:
        if propios:
            clientes.cerrar()
    return corridas


def ejecutar_en_segundo_plano(corrida_ids: Sequence[int]) -> None:
    """Tarea de fondo de ``POST /ingestas/ejecutar`` (sesiones y clientes propios)."""
    ejecutar_en_sesiones(list(corrida_ids))


def cerrar_colgadas(db: Session) -> list[tuple[int, str, dt.date | None]]:
    """Cierra como interrumpidas las corridas en curso sin latido en :data:`MINUTOS_SIN_LATIDO`
    minutos. Devuelve ``(id, fuente, fecha_programada)`` de cada una."""
    ahora = ahora_utc()
    return repo.cerrar_colgadas(db, ahora - dt.timedelta(minutes=MINUTOS_SIN_LATIDO), ahora)


# --- Reproceso de WeatherLink ---------------------------------------------------

@dataclass
class ResultadoReproceso:
    corrida_id: int
    dias_con_crudo: int
    dias_sin_crudo: list[dt.date]
    lecturas: int
    conteo: ConteoUpsert
    borradas: int
    ambiente: ambiente_service.ResultadoAmbiente | None


def _auditar_excel_pisado(
    db: Session, corrida_id: int, desde: dt.date, hasta: dt.date, pisadas: list[dt.datetime]
) -> None:
    por_dia: dict[str, int] = {}
    for fecha_hora in pisadas:
        clave = fecha_hora.date().isoformat()
        por_dia[clave] = por_dia.get(clave, 0) + 1
    auditoria_service.registrar(
        db, accion=auditoria_service.METEO_EXCEL_PISADO,
        entidad=auditoria_service.ENTIDAD_INGESTA_CORRIDA, entidad_id=corrida_id,
        actor_username=auditoria_service.ACTOR_SISTEMA,
        detalle={"desde": desde.isoformat(), "hasta": hasta.isoformat(),
                 "lecturas_reemplazadas": len(pisadas), "por_dia": por_dia},
    )


def registros_de_crudos(crudos: Sequence[Any], desde: dt.date, hasta: dt.date) -> list[dict[str, Any]]:
    """Registros de los payloads que pertenecen a ``desde..hasta`` con el corte de día actual de
    ``conversion``. Un mismo ``ts`` puede venir en dos payloads (días vecinos pedidos con otro
    corte): queda el del payload más reciente."""
    por_ts: dict[Any, dict[str, Any]] = {}
    for crudo in sorted(crudos, key=lambda c: c.id):
        for registro in conversion.registros_de_payload(crudo.payload):
            dia = conversion.dia_de_registro(registro)
            if dia is not None and desde <= dia <= hasta:
                por_ts[registro[conversion.CAMPO_TS]] = registro
    return list(por_ts.values())


MAX_DIAS_PISAR_EXCEL = 31


def reprocesar_weatherlink(
    db: Session, desde: dt.date, hasta: dt.date, *, pisar_excel: bool = False
) -> ResultadoReproceso:
    """Vuelve a derivar ``meteo_lectura`` (origen ``weatherlink``) desde los payloads guardados en
    ``ingesta_crudo`` con las reglas actuales de ``conversion`` y recalcula ``ambiente_diario``.
    Sin descargar nada. Las lecturas del Excel histórico no se tocan.

    Se leen también los payloads del día anterior y del siguiente: con otro corte de día (p. ej.
    los descargados antes de ``MEDIANOCHE_AL_DIA_QUE_TERMINA``) el registro de las 24:00 de un día
    está en el payload del día siguiente. Las lecturas ``weatherlink`` de ``desde..hasta`` que ya
    no salen de los payloads (etiquetas de la regla anterior) se borran.

    ``pisar_excel`` (rango de hasta :data:`MAX_DIAS_PISAR_EXCEL` días): las lecturas de WeatherLink
    reemplazan también las del Excel histórico de esos días (p. ej. un error conocido del Excel) y
    queda en la auditoría cuántas se reemplazaron por día. Las lecturas del Excel sin par en
    WeatherLink no se tocan."""
    if desde > hasta:
        raise ValueError("desde debe ser anterior o igual a hasta")
    if pisar_excel and (hasta - desde).days + 1 > MAX_DIAS_PISAR_EXCEL:
        raise ValueError(f"Con --pisar-excel el rango no puede superar {MAX_DIAS_PISAR_EXCEL} días")
    inicio = time.monotonic()
    fundo = fundo_de_datos(db)
    corrida = repo_datos.nueva_corrida(
        db, fuente=FUENTE_REPROCESAR, disparo=DisparoIngesta.script, inicio_at=ahora_utc(),
        estado=EstadoIngesta.en_curso, desde=desde, hasta=hasta,
    )
    uno = dt.timedelta(days=1)
    crudos = repo.crudos_weatherlink(db, desde - uno, hasta + uno)
    dias = {d for c in crudos if desde <= (d := dt.date.fromisoformat(c.parametros["dia"])) <= hasta}
    registros = registros_de_crudos(crudos, desde, hasta)
    resultado = ResultadoFuente(llamadas_ok=len(crudos))
    pisadas: list[dt.datetime] = []
    if registros and pisar_excel:
        etiquetas = {conversion.fecha_hora_local(r[conversion.CAMPO_TS]).to_pydatetime() for r in registros}
        pisadas = repo_datos.lecturas_por_origen(db, fundo.id, OrigenMeteo.excel_historico, etiquetas)
    if registros:
        guardar_lecturas_weatherlink(db, fundo, registros, corrida.id, resultado, pisar_excel=pisar_excel)
    if pisar_excel:
        _auditar_excel_pisado(db, corrida.id, desde, hasta, pisadas)
    conservar = {conversion.fecha_hora_local(r[conversion.CAMPO_TS]).to_pydatetime() for r in registros}
    # Solo en los días con payload (propio o del vecino): los días sin crudo no se tocan.
    borradas = repo_datos.borrar_meteo_sobrante(
        db, fundo.id, OrigenMeteo.weatherlink, dt.datetime.combine(desde, dt.time()),
        dt.datetime.combine(hasta + uno, dt.time()), conservar, dias | {f.date() for f in conservar},
    )
    resultado.fechas |= {f.date() for f in borradas}
    ambiente = ambiente_service.recalcular(db, fundo, resultado.fechas) if resultado.fechas else None
    corrida.estado = EstadoIngesta.ok
    corrida.filas_nuevas = resultado.conteo.nuevas
    corrida.filas_actualizadas = resultado.conteo.actualizadas + len(borradas)
    corrida.filas_omitidas = resultado.conteo.omitidas
    corrida.fin_at = ahora_utc()
    corrida.duracion_ms = int((time.monotonic() - inicio) * 1000)
    db.flush()
    return ResultadoReproceso(
        corrida_id=corrida.id, dias_con_crudo=len(dias),
        dias_sin_crudo=[d for d in _dias(desde, hasta) if d not in dias],
        lecturas=len(registros), conteo=resultado.conteo, borradas=len(borradas), ambiente=ambiente,
    )
