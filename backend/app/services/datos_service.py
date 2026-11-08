"""Lectura de datos de campo: frescura por fuente (§3.3), series para gráficos y turnos con
caudal reciente. Solo lectura (sin efectos secundarios).

Frescura (panel del Dashboard): para cada fuente, la **última fecha completa** hasta D-1
(``referencia = fecha − 1``) y verde si llega a D-1, naranja si no. Se evalúa cada día de la
ventana ``[fecha − dias, D-1]`` y se informan los huecos intermedios (días sin dato anteriores a la
última fecha completa):

- ``riego_aplicado``: el día está completo si **todos** los turnos activos del módulo tienen un
  registro vigente aplicado (un ``sin_riego`` cuenta). Detalle por turno en ``por_turno``.
- ``riego_provisional``: igual, pero cuenta también el riego provisional.
- ``weatherlink``: ``ambiente_diario.tiene_meteo`` (``meteo_diaria`` exige 36 de 48 lecturas).
- ``phytech_suelo``: ``hum_zona_radicular_cierre`` no nulo.
- ``phytech_planta``: ``tiene_planta`` (MDS del día).
- ``ndvi`` y ``pronostico``: informativos (última imagen / última captura), sin verde/naranja.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import DatosInvalidos, NoEncontrado
from app.core.tiempo import fuera_de_limites, hoy_lima, mensaje_fuera_de_limites
from app.models import Modulo
from app.models.enums import EstadoRiego
from app.repositories import datos_series as repo
from app.schemas.datos import FuenteFrescura, FrescuraSalida, SerieSalida, TurnoCaudalSalida, TurnoFrescura

DIAS_FRESCURA = 7
MAX_DIAS_FRESCURA = 60
DIAS_SERIE = 14
MAX_DIAS_SERIE_DIARIA = 366
MAX_DIAS_SERIE_DETALLE = 31
DIAS_CAUDAL = 30

NOMBRES = {
    "riego_aplicado": "Riego aplicado",
    "riego_provisional": "Riego provisional",
    "weatherlink": "WeatherLink (clima)",
    "phytech_suelo": "Phytech suelo",
    "phytech_planta": "Phytech planta",
    "ndvi": "NDVI",
    "pronostico": "Pronóstico Phytech",
}


def modulo_o_404(db: Session, modulo_id: int) -> Modulo:
    modulo = db.get(Modulo, modulo_id)
    if modulo is None or not modulo.activo:
        raise NoEncontrado("Módulo no encontrado")
    return modulo


def validar_fechas(*fechas: dt.date | None) -> None:
    """422 si alguna fecha pedida está fuera de los límites (``app.core.tiempo``)."""
    if fuera_de_limites(*fechas) is not None:
        raise DatosInvalidos(mensaje_fuera_de_limites())


def _dias(desde: dt.date, hasta: dt.date) -> list[dt.date]:
    return [desde + dt.timedelta(days=i) for i in range((hasta - desde).days + 1)]


def _estado(ultima: dt.date | None, referencia: dt.date) -> str:
    return "verde" if ultima is not None and ultima >= referencia else "naranja"


def _huecos(ventana: list[dt.date], con_dato: set[dt.date], ultima: dt.date | None) -> list[dt.date]:
    if ultima is None:
        return []
    return [d for d in ventana if d <= ultima and d not in con_dato]


def _riego(db: Session, modulo: Modulo, ventana: list[dt.date], referencia: dt.date, *,
           solo_aplicado: bool) -> FuenteFrescura:
    fuente = "riego_aplicado" if solo_aplicado else "riego_provisional"
    turnos = repo.turnos_activos(db, modulo.id)
    ultimas = repo.ultimo_riego_por_turno(db, modulo.id, referencia, solo_aplicado=solo_aplicado)
    en_ventana: dict[int, set[dt.date]] = {}
    for turno_id, fecha, estado in repo.riego_en_ventana(db, modulo.id, ventana[0], ventana[-1]):
        if solo_aplicado and estado != EstadoRiego.aplicado:
            continue
        en_ventana.setdefault(turno_id, set()).add(fecha)
    por_turno = [
        TurnoFrescura(turno_id=t.id, turno_codigo=t.codigo, ultima_fecha=ultimas.get(t.id),
                      huecos=_huecos(ventana, en_ventana.get(t.id, set()), ultimas.get(t.id)))
        for t in turnos
    ]
    if not turnos or any(t.ultima_fecha is None for t in por_turno):
        ultima = None
    else:
        ultima = min(t.ultima_fecha for t in por_turno)
    completos = {d for d in ventana if turnos and all(d in en_ventana.get(t.id, set()) for t in turnos)}
    detalle = None if solo_aplicado else "Cuenta el riego aplicado y el provisional"
    return FuenteFrescura(
        fuente=fuente, nombre=NOMBRES[fuente], ultima_fecha=ultima, estado=_estado(ultima, referencia),
        huecos=_huecos(ventana, completos, ultima), detalle=detalle, por_turno=por_turno,
    )


def _ambiente(db: Session, fundo_id: int, fuente: str, ventana: list[dt.date],
              referencia: dt.date) -> FuenteFrescura:
    ultima = repo.ultima_fecha_ambiente(db, fundo_id, fuente, referencia)
    con_dato = repo.fechas_ambiente(db, fundo_id, fuente, ventana[0], ventana[-1])
    return FuenteFrescura(
        fuente=fuente, nombre=NOMBRES[fuente], ultima_fecha=ultima, estado=_estado(ultima, referencia),
        huecos=_huecos(ventana, con_dato, ultima),
    )


def frescura(db: Session, modulo_id: int, fecha: dt.date | None = None,
             dias: int = DIAS_FRESCURA) -> FrescuraSalida:
    validar_fechas(fecha)
    modulo = modulo_o_404(db, modulo_id)
    fecha = fecha or hoy_lima()
    referencia = fecha - dt.timedelta(days=1)
    ventana = _dias(fecha - dt.timedelta(days=dias), referencia)
    fundo_id = modulo.fundo_id
    fuentes = [
        _riego(db, modulo, ventana, referencia, solo_aplicado=True),
        _riego(db, modulo, ventana, referencia, solo_aplicado=False),
        *(_ambiente(db, fundo_id, f, ventana, referencia)
          for f in ("weatherlink", "phytech_suelo", "phytech_planta")),
        FuenteFrescura(
            fuente="ndvi", nombre=NOMBRES["ndvi"], informativa=True, estado="informativo",
            ultima_fecha=repo.ultima_ndvi(db, fundo_id, settings.phytech_plot_id, referencia),
            detalle="Imagen satelital cada pocos días (los días nublados no hay)",
        ),
        FuenteFrescura(
            fuente="pronostico", nombre=NOMBRES["pronostico"], informativa=True, estado="informativo",
            ultima_fecha=repo.ultima_captura(db, settings.phytech_project_id, fecha),
            detalle="Fecha de la última captura del pronóstico",
        ),
    ]
    return FrescuraSalida(modulo_id=modulo.id, fecha=fecha, referencia=referencia, dias=dias, fuentes=fuentes)


# --- Series ---------------------------------------------------------------------

def rango_serie(desde: dt.date | None, hasta: dt.date | None, maximo: int) -> tuple[dt.date, dt.date]:
    """Por defecto los últimos 14 días cerrados."""
    validar_fechas(desde, hasta)
    hasta = hasta or (hoy_lima() - dt.timedelta(days=1))
    desde = desde or (hasta - dt.timedelta(days=DIAS_SERIE - 1))
    if desde > hasta:
        raise DatosInvalidos("«desde» debe ser anterior o igual a «hasta»")
    if (hasta - desde).days + 1 > maximo:
        raise DatosInvalidos(f"El rango no puede superar {maximo} días para esta resolución")
    return desde, hasta


def _fundo_id(db: Session, modulo_id: int | None) -> int:
    if modulo_id is not None:
        return modulo_o_404(db, modulo_id).fundo_id
    from app.services.ingesta_service import fundo_de_datos

    return fundo_de_datos(db).id


def _intervalo(desde: dt.date, hasta: dt.date) -> tuple[dt.datetime, dt.datetime]:
    return dt.datetime.combine(desde, dt.time()), dt.datetime.combine(hasta + dt.timedelta(days=1), dt.time())


def _fila(objeto: Any, columnas: tuple[str, ...]) -> dict[str, Any]:
    return {c: getattr(objeto, c) for c in columnas}


CLIMA_DIARIO = ("t_media", "t_max", "t_min", "hr_media", "hr_min", "hr_max", "eto_mm", "dpv_media",
                "dpv_max", "viento_media", "lluvia_mm", "rad_max", "rad_media", "horas_t30",
                "meteo_lecturas", "tiene_meteo")
CLIMA_30MIN = ("temp", "temp_max", "temp_min", "hr", "hr_max", "rad", "eto", "dpv", "viento", "lluvia")
UNIDADES_CLIMA = {"t": "°C", "hr": "%", "eto": "mm", "dpv": "kPa", "viento": "km (por 30 min)",
                  "lluvia": "mm", "rad": "W/m²"}


def serie_clima(db: Session, *, desde: dt.date | None, hasta: dt.date | None, resolucion: str,
                modulo_id: int | None = None) -> SerieSalida:
    fundo_id = _fundo_id(db, modulo_id)
    if resolucion == "30min":
        desde, hasta = rango_serie(desde, hasta, MAX_DIAS_SERIE_DETALLE)
        inicio, fin = _intervalo(desde, hasta)
        puntos = [{"fecha_hora": f.fecha_hora, **_fila(f, CLIMA_30MIN), "origen": f.origen.value}
                  for f in repo.meteo(db, fundo_id, inicio, fin)]
    else:
        desde, hasta = rango_serie(desde, hasta, MAX_DIAS_SERIE_DIARIA)
        puntos = [{"fecha": f.fecha, **_fila(f, CLIMA_DIARIO)}
                  for f in repo.ambiente(db, fundo_id, desde, hasta)]
    return SerieSalida(fuente="clima", resolucion=resolucion, desde=desde, hasta=hasta,
                       unidades=UNIDADES_CLIMA, puntos=puntos)


SUELO_DIARIO = ("hum_15cm_media", "hum_30cm_media", "hum_45cm_media", "hum_60cm_media",
                "hum_75cm_media", "hum_90cm_media", "hum_zona_radicular_media", "hum_linea_estres_media",
                "hum_zona_radicular_cierre", "hum_linea_estres_cierre", "hum_45cm_rango",
                "hum_60cm_rango", "suelo_horas", "tiene_suelo")
SUELO_HORARIO = ("hay_dato", "hum_15cm", "hum_30cm", "hum_45cm", "hum_60cm", "hum_75cm", "hum_90cm",
                 "temp_15cm", "temp_30cm", "temp_60cm", "temp_90cm", "hum_zona_radicular",
                 "hum_saturacion", "hum_linea_estres", "hum_zona_radicular_norm_pct")


def serie_suelo(db: Session, *, desde: dt.date | None, hasta: dt.date | None, resolucion: str,
                modulo_id: int | None = None) -> SerieSalida:
    if resolucion == "horaria":
        desde, hasta = rango_serie(desde, hasta, MAX_DIAS_SERIE_DETALLE)
        inicio, fin = _intervalo(desde, hasta)
        puntos = [{"fecha_hora": f.fecha_hora, **_fila(f, SUELO_HORARIO)}
                  for f in repo.suelo(db, settings.phytech_project_id, inicio, fin)]
    else:
        fundo_id = _fundo_id(db, modulo_id)
        desde, hasta = rango_serie(desde, hasta, MAX_DIAS_SERIE_DIARIA)
        puntos = [{"fecha": f.fecha, **_fila(f, SUELO_DIARIO)}
                  for f in repo.ambiente(db, fundo_id, desde, hasta)]
    return SerieSalida(fuente="suelo", resolucion=resolucion, desde=desde, hasta=hasta,
                       unidades={"hum": "% vol.", "temp": "°C"}, puntos=puntos)


PLANTA = ("mds_contraccion_um", "crecimiento_tronco_um", "estres_planta_ps", "tamano_fruto_mm",
          "crecimiento_fruto_mm", "et_mm", "lluvia_mm")


def serie_planta(db: Session, *, desde: dt.date | None, hasta: dt.date | None) -> SerieSalida:
    desde, hasta = rango_serie(desde, hasta, MAX_DIAS_SERIE_DIARIA)
    puntos = [{"fecha": f.fecha, **_fila(f, PLANTA)}
              for f in repo.planta(db, settings.phytech_project_id, desde, hasta)]
    return SerieSalida(fuente="planta", resolucion="diaria", desde=desde, hasta=hasta,
                       unidades={"mds": "µm", "crecimiento_tronco": "µm", "ps": "índice", "et": "mm",
                                 "lluvia": "mm"}, puntos=puntos)


def serie_pronostico(db: Session, *, desde: dt.date | None, hasta: dt.date | None,
                     capturado: dt.date | None) -> SerieSalida:
    """La captura indicada (por defecto la última hasta hoy), filtrada por ``desde``/``hasta``."""
    if desde and hasta and desde > hasta:
        raise DatosInvalidos("«desde» debe ser anterior o igual a «hasta»")
    capturado = capturado or repo.ultima_captura(db, settings.phytech_project_id, hoy_lima())
    filas = [] if capturado is None else repo.pronostico(db, settings.phytech_project_id, capturado, desde, hasta)
    return SerieSalida(
        fuente="pronostico", resolucion="diaria", desde=desde, hasta=hasta, capturado_fecha=capturado,
        unidades={"t_max": "°C", "eto_mm": "mm", "etc_mm": "mm", "humedad": "%"},
        puntos=[{"fecha": f.fecha, "t_max": f.t_max, "eto_mm": f.eto_mm, "etc_mm": f.etc_mm,
                 "humedad": f.humedad} for f in filas],
    )


# --- Turnos ---------------------------------------------------------------------

def turnos_con_caudal(db: Session, modulo_id: int) -> list[TurnoCaudalSalida]:
    modulo = modulo_o_404(db, modulo_id)
    hasta = hoy_lima() - dt.timedelta(days=1)
    caudales = repo.caudal_reciente(db, modulo.id, hasta - dt.timedelta(days=DIAS_CAUDAL - 1), hasta)
    salida = []
    for turno in repo.turnos_activos(db, modulo.id):
        caudal = caudales.get(turno.id, {})
        salida.append(TurnoCaudalSalida(
            id=turno.id, codigo=turno.codigo, orden=turno.orden, area_ha=turno.area_ha,
            valvula_controlador=turno.valvula_controlador, valvula_siga=turno.valvula_siga,
            caudal_m3h=caudal.get("caudal_m3h"), factor_min_por_m3ha=caudal.get("factor_min_por_m3ha"),
            ciclos_considerados=caudal.get("ciclos", 0), ultimo_riego_aplicado=caudal.get("ultima_fecha"),
        ))
    return salida
