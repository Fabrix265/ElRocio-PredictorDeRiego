"""Copiloto agrónomo: resumen diario y alertas para el agente de n8n (y la vista Copiloto).

Todo lo que el agente cuenta sale de aquí, ya calculado: el LLM solo redacta. Las reglas son
deterministas y configurables (``COPILOTO_*`` en ``app.core.config``):

- ``plan_hoy_*`` / ``plan_manana_*``: no hay plan, sigue en borrador o tiene corrección pedida.
- ``datos_atrasados``: una fuente (riego registrado, WeatherLink, Phytech suelo/planta) no llega
  a D-1.
- ``desvio_plan_real``: lo regado se aleja más de ``COPILOTO_DESVIO_PCT`` de lo propuesto en un
  turno (último día con riego aplicado de los 3 anteriores).
- ``estres_mds`` / ``estres_suelo``: ``COPILOTO_DIAS_ESTRES`` días seguidos (hasta el último día
  con datos) con MDS ≥ umbral alto, o con la zona radicular bajo la línea de estrés.
- ``riego_sin_respuesta``: se regó, pero la humedad de la zona radicular casi no subió
  (posible gotero tapado, válvula o fuga). ``humedad_sin_riego``: la humedad subió como en un día
  de riego, pero no hay riego registrado (¿falta cargarlo?). Ambas comparan la subida del día
  (máximo − mínimo antes de las 06:00) con la mediana de los 14 días anteriores con riego.
- ``demanda_alta``: el pronóstico de Phytech trae una ETo bastante mayor que la de la última semana.

Solo lectura: nada de esto modifica cronogramas ni riego.
"""

from __future__ import annotations

import datetime as dt
import statistics
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import DatosInvalidos
from app.core.tiempo import ahora_lima, hoy_lima
from app.models import AmbienteDiario, Cronograma, Modulo, TokenServicio, Turno, Usuario
from app.models.enums import EstadoCronograma, RolUsuario
from app.repositories import copiloto as repo
from app.repositories import cronogramas as repo_crono
from app.repositories import datos_series as repo_series
from app.repositories import riego as repo_riego
from app.services import datos_service, reportes_service

SEVERIDADES = ("alta", "media", "info")
DIAS_CONTEXTO = 7
DIAS_MEDIANA_SUELO = 14
DIAS_BUSCAR_DATO = 3
MAX_DIAS_CLIMA = 31
# Respuesta del suelo: m³/ha mínimos para considerar el día «regado» y umbrales relativos a la
# mediana de las subidas de días regados (calibrados con la sonda del MOD5: ~3 % vol. por día).
RIEGO_MINIMO_M3HA = 10.0
SIN_RIEGO_MAXIMO_M3HA = 2.0
FRACCION_SIN_RESPUESTA = 0.35
SUBIDA_MINIMA_SIN_RESPUESTA = 0.5
FRACCION_SIN_RIEGO = 0.6
SUBIDA_MINIMA_SIN_RIEGO = 1.5
# Pronóstico: ETo máxima de los próximos días frente a la media de la última semana.
FACTOR_DEMANDA_ALTA = 1.2
ETO_MINIMA_DEMANDA_ALTA = 4.0
DIAS_PRONOSTICO = 5
ETIQUETA_ESTADO = {
    EstadoCronograma.borrador: "borrador (sin publicar)",
    EstadoCronograma.publicado: "publicado",
    EstadoCronograma.visto: "publicado y visto por el programador",
    EstadoCronograma.correccion_solicitada: "con corrección solicitada por el subgerente",
}


@dataclass(frozen=True)
class Lector:
    """Quién consulta: el agente (token de servicio) o un usuario de la app.

    El agente lee como el subgerente: ve la propuesta del modelo, nunca escribe en cronogramas.
    """

    usuario: Usuario | None = None
    token: TokenServicio | None = None

    @property
    def rol(self) -> RolUsuario:
        return self.usuario.rol if self.usuario is not None else RolUsuario.subgerente

    @property
    def es_agente(self) -> bool:
        return self.token is not None


# --- Utilidades -----------------------------------------------------------------


def _f(fecha: dt.date) -> str:
    """Fecha para los textos de las alertas, como en la app: 07/11/2026."""
    return fecha.strftime("%d/%m/%Y")


def _r(valor: float | None, decimales: int = 1) -> float | None:
    return None if valor is None else round(float(valor), decimales)


def modulo_de(db: Session, modulo_id: int | None) -> Modulo:
    """El módulo pedido o, si no se indica, el único activo (como el MOD5 de hoy)."""
    if modulo_id is not None:
        return datos_service.modulo_o_404(db, modulo_id)
    activos = repo.modulos_activos(db)
    if len(activos) != 1:
        raise DatosInvalidos("Indica modulo_id: hay más de un módulo activo")
    return activos[0]


def nivel_mds(mds: float | None) -> str | None:
    if mds is None:
        return None
    if mds >= settings.copiloto_mds_critico_um:
        return "critico"
    if mds >= settings.copiloto_mds_alto_um:
        return "alto"
    if mds >= settings.copiloto_mds_moderado_um:
        return "moderado"
    return "sin_estres"


def _alerta(codigo: str, severidad: str, titulo: str, detalle: str, *, fecha: dt.date | None = None,
            turno_codigo: str | None = None, **valores: Any) -> dict[str, Any]:
    return {"codigo": codigo, "severidad": severidad, "titulo": titulo, "detalle": detalle,
            "fecha": fecha, "turno_codigo": turno_codigo, "valores": valores}


def umbrales() -> dict[str, Any]:
    return {
        "desvio_pct": settings.copiloto_desvio_pct,
        "dias_estres": settings.copiloto_dias_estres,
        "mds_um": {"moderado": settings.copiloto_mds_moderado_um, "alto": settings.copiloto_mds_alto_um,
                   "critico": settings.copiloto_mds_critico_um},
        "margen_estres_suelo_pct_vol": settings.copiloto_margen_estres_suelo,
        "hora_plan_manana": settings.copiloto_hora_plan_manana,
    }


# --- Plan de un día ---------------------------------------------------------------


def plan_del_dia(db: Session, modulo: Modulo, fecha: dt.date, turnos: list[Turno] | None = None) -> dict[str, Any] | None:
    """Plan del día por turno con m³, m³/ha, horario y ETo. Usa la versión publicada; si no hay,
    el borrador. ``None`` si no hay cronograma."""
    crono = repo_crono.por_fecha(db, modulo.id, fecha)
    if crono is None:
        return None
    turnos = turnos if turnos is not None else repo_riego.turnos_de_modulo(db, modulo.id)
    version = repo_crono.version(db, crono.version_publicada_id or crono.borrador_version_id)
    eto = repo_crono.eto_por_fecha(db, modulo.fundo_id, [fecha - dt.timedelta(days=1), fecha])
    eto_ant, eto_dia = eto.get(fecha - dt.timedelta(days=1)), eto.get(fecha)
    salida: dict[str, Any] = {
        "fecha": fecha, "cronograma_id": crono.id, "estado": crono.estado.value,
        "estado_texto": ETIQUETA_ESTADO.get(crono.estado, crono.estado.value),
        "publicado": crono.version_publicada_id is not None,
        "borrador_pendiente": crono.version_publicada_id is not None and crono.borrador_version_id is not None,
        "version": version.numero if version else None,
        "origen_version": version.origen.value if version else None,
        "eto_dia_anterior_mm": _r(eto_ant[0], 2) if eto_ant else None,
        "eto_dia_anterior_es_pronostico": eto_ant[1] if eto_ant else None,
        "eto_pronostico_mm": _r(eto_dia[0], 2) if eto_dia else None,
        "total_m3": None, "total_m3ha": None, "turnos": [],
    }
    if version is None:
        return salida
    por_turno: dict[int, list[Any]] = {}
    for c in version.ciclos:
        por_turno.setdefault(c.turno_id, []).append(c)
    total_m3 = total_area = 0.0
    for t in turnos:
        ciclos = sorted(por_turno.get(t.id, []), key=lambda c: c.inicio_min)
        m3 = sum(c.riego_m3 for c in ciclos)
        m3ha = sum(c.riego_m3ha for c in ciclos)
        if ciclos:
            total_m3 += m3
            total_area += t.area_ha
        salida["turnos"].append({
            "turno_codigo": t.codigo, "area_ha": _r(t.area_ha, 2), "n_ciclos": len(ciclos),
            "m3": _r(m3, 1), "m3ha": _r(m3ha, 2),
            "inicio": ciclos[0].hora_inicio if ciclos else None,
            "fin": ciclos[-1].hora_fin if ciclos else None,
            "ciclos": [{"ciclo": i + 1, "hora_inicio": c.hora_inicio, "hora_fin": c.hora_fin,
                        "duracion_min": _r(c.duracion_min, 0), "m3": _r(c.riego_m3, 1),
                        "m3ha": _r(c.riego_m3ha, 2)} for i, c in enumerate(ciclos)],
        })
    salida["total_m3"] = _r(total_m3, 1)
    salida["total_m3ha"] = _r(total_m3 / total_area, 2) if total_area else None
    return salida


# --- Agua aplicada vs propuesta ---------------------------------------------------


def agua(db: Session, modulo: Modulo, desde: dt.date | None, hasta: dt.date | None, lector: Lector,
         turno_codigo: str | None = None) -> dict[str, Any]:
    """Versión compacta de ``reportes_service.agua`` con totales por turno y del módulo."""
    datos = reportes_service.agua(db, modulo.id, desde, hasta, lector)  # type: ignore[arg-type]
    codigo = turno_codigo.strip().upper() if turno_codigo else None
    if codigo and codigo not in {t["turno_codigo"] for d in datos["dias"] for t in d["turnos"]}:
        raise DatosInvalidos(f"El turno {codigo} no existe en el módulo")
    dias, totales = [], {}
    for d in datos["dias"]:
        filas = []
        for t in d["turnos"]:
            if codigo and t["turno_codigo"] != codigo:
                continue
            fila = {"turno_codigo": t["turno_codigo"], "area_ha": t["area_ha"],
                    "propuesto_m3": t["propuesto_m3"], "propuesto_m3ha": t["propuesto_m3ha"],
                    "aplicado_m3": t["aplicado_m3"], "aplicado_m3ha": t["aplicado_m3ha"],
                    "estado_riego": t["estado_riego"], "sin_riego": t["sin_riego"]}
            if datos["con_modelo"]:
                fila["modelo_m3ha"] = t["modelo_m3ha"]
            filas.append(fila)
            acum = totales.setdefault(t["turno_codigo"], {"turno_codigo": t["turno_codigo"], "area_ha": t["area_ha"],
                                                          "propuesto_m3": 0.0, "aplicado_m3": 0.0,
                                                          "dias_con_propuesta": 0, "dias_con_riego": 0})
            if t["propuesto_m3"] is not None:
                acum["propuesto_m3"] += t["propuesto_m3"]
                acum["dias_con_propuesta"] += 1
            if t["aplicado_m3"] is not None:
                acum["aplicado_m3"] += t["aplicado_m3"]
                acum["dias_con_riego"] += 1
        dias.append({"fecha": d["fecha"], "modificado": d["modificado"], "motivo": d["motivo"], "turnos": filas})

    def _total(m3: float, area: float | None, hay: bool) -> tuple[float | None, float | None]:
        # Sin ningún día con dato es «sin dato», no 0 m³.
        if not hay:
            return None, None
        return _r(m3), (_r(m3 / area, 2) if area else None)

    por_turno = []
    for acum in totales.values():
        area = acum["area_ha"] or None
        prop_m3, prop_m3ha = _total(acum["propuesto_m3"], area, acum["dias_con_propuesta"] > 0)
        apl_m3, apl_m3ha = _total(acum["aplicado_m3"], area, acum["dias_con_riego"] > 0)
        por_turno.append({**acum, "propuesto_m3": prop_m3, "propuesto_m3ha": prop_m3ha,
                          "aplicado_m3": apl_m3, "aplicado_m3ha": apl_m3ha})
    area_total = sum(t["area_ha"] for t in por_turno) or None
    aplicado_m3, aplicado_m3ha = _total(sum(t["aplicado_m3"] or 0 for t in por_turno), area_total,
                                        any(t["dias_con_riego"] for t in por_turno))
    propuesto_m3, propuesto_m3ha = _total(sum(t["propuesto_m3"] or 0 for t in por_turno), area_total,
                                          any(t["dias_con_propuesta"] for t in por_turno))
    return {
        "modulo_codigo": modulo.codigo, "desde": datos["desde"], "hasta": datos["hasta"], "turno": codigo,
        "totales": {"aplicado_m3": aplicado_m3, "aplicado_m3ha": aplicado_m3ha,
                    "propuesto_m3": propuesto_m3, "propuesto_m3ha": propuesto_m3ha},
        "por_turno": por_turno, "dias": dias,
    }


# --- Clima, planta y suelo --------------------------------------------------------


def _fila_clima(a: AmbienteDiario) -> dict[str, Any]:
    return {
        "fecha": a.fecha, "eto_mm": _r(a.eto_mm, 2), "t_max": _r(a.t_max), "t_min": _r(a.t_min),
        "hr_media": _r(a.hr_media), "lluvia_mm": _r(a.lluvia_mm), "dpv_max": _r(a.dpv_max, 2),
        "mds_um": _r(a.mds_contraccion_um, 0), "nivel_mds": nivel_mds(a.mds_contraccion_um),
        "crecimiento_tronco_um": _r(a.crecimiento_tronco_um, 0),
        "hum_zona_radicular_cierre": _r(a.hum_zona_radicular_cierre, 2),
        "hum_linea_estres": _r(a.hum_linea_estres_cierre, 2), "ndvi": _r(a.ndvi_medio, 3),
    }


def pronostico(db: Session, desde: dt.date, dias: int = DIAS_PRONOSTICO) -> dict[str, Any]:
    serie = datos_service.serie_pronostico(db, desde=desde, hasta=desde + dt.timedelta(days=dias - 1), capturado=None)
    vistos, puntos = set(), []
    for p in serie.puntos:
        if p["fecha"] in vistos:
            continue
        vistos.add(p["fecha"])
        puntos.append({"fecha": p["fecha"], "eto_mm": _r(p["eto_mm"], 2), "etc_mm": _r(p["etc_mm"], 2),
                       "t_max": _r(p["t_max"]), "humedad": _r(p["humedad"])})
    return {"fuente": "Phytech", "capturado_fecha": serie.capturado_fecha, "dias": puntos}


def clima(db: Session, modulo: Modulo, desde: dt.date | None, hasta: dt.date | None) -> dict[str, Any]:
    datos_service.validar_fechas(desde, hasta)
    hasta = hasta or hoy_lima() - dt.timedelta(days=1)
    desde = desde or hasta - dt.timedelta(days=DIAS_CONTEXTO - 1)
    if desde > hasta:
        raise DatosInvalidos("«desde» debe ser anterior o igual a «hasta»")
    if (hasta - desde).days + 1 > MAX_DIAS_CLIMA:
        raise DatosInvalidos(f"El rango no puede superar {MAX_DIAS_CLIMA} días")
    filas = repo_series.ambiente(db, modulo.fundo_id, desde, hasta)
    return {
        "desde": desde, "hasta": hasta,
        "unidades": {"eto_mm": "mm", "t": "°C", "hr": "%", "lluvia": "mm", "dpv": "kPa", "mds": "µm",
                     "humedad_suelo": "% vol."},
        "dias": [_fila_clima(a) for a in filas],
        "pronostico": pronostico(db, hoy_lima()),
    }


# --- Reglas -------------------------------------------------------------------------


def _alertas_plan(crono: Cronograma | None, plan: dict[str, Any] | None, fecha: dt.date, *,
                  es_hoy: bool) -> list[dict[str, Any]]:
    cual = "hoy" if es_hoy else "mañana"
    sufijo = "hoy" if es_hoy else "manana"
    tarde = ahora_lima().hour >= settings.copiloto_hora_plan_manana
    if crono is None or plan is None:
        severidad = "alta" if es_hoy else ("media" if tarde else "info")
        return [_alerta(f"plan_{sufijo}_sin_generar", severidad, f"No hay plan de riego para {cual}",
                        f"No se ha generado el cronograma del {_f(fecha)}.", fecha=fecha)]
    if crono.estado == EstadoCronograma.correccion_solicitada:
        return [_alerta(f"plan_{sufijo}_correccion", "media", f"El plan de {cual} tiene una corrección pedida",
                        f"Motivo: {crono.correccion_solicitada_motivo or 'sin detalle'}.", fecha=fecha)]
    if not plan["publicado"]:
        severidad = "alta" if es_hoy else ("media" if tarde else "info")
        return [_alerta(f"plan_{sufijo}_sin_publicar", severidad, f"El plan de {cual} sigue en borrador",
                        f"El cronograma del {_f(fecha)} aún no se publica al programador.", fecha=fecha)]
    return []


def _alertas_frescura(db: Session, modulo: Modulo, fecha: dt.date) -> list[dict[str, Any]]:
    salida = []
    frescura = datos_service.frescura(db, modulo.id, fecha)
    for f in frescura.fuentes:
        if f.informativa or f.estado != "naranja" or f.fuente == "riego_aplicado":
            continue
        atraso = None if f.ultima_fecha is None else (frescura.referencia - f.ultima_fecha).days
        severidad = "alta" if atraso is None or atraso >= 2 else "media"
        nombre = "Riego registrado" if f.fuente == "riego_provisional" else f.nombre
        detalle = (f"Sin datos de {nombre}." if f.ultima_fecha is None else
                   f"Último dato completo: {_f(f.ultima_fecha)} ({atraso} día(s) de atraso respecto de "
                   f"{_f(frescura.referencia)}).")
        salida.append(_alerta("datos_atrasados", severidad, f"{nombre}: datos atrasados", detalle,
                              fecha=frescura.referencia, fuente=f.fuente, ultima_fecha=f.ultima_fecha,
                              dias_atraso=atraso))
    return salida


def _alertas_desvio(agua_dias: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Último día (de los 3 anteriores) con riego aplicado y propuesta: turnos fuera de ±umbral."""
    umbral = settings.copiloto_desvio_pct
    for dia in reversed(agua_dias):
        filas = [t for t in dia["turnos"] if t["estado_riego"] == "aplicado" and t["propuesto_m3ha"]]
        if not filas:
            continue
        salida = []
        for t in filas:
            real = 0.0 if t["sin_riego"] else (t["aplicado_m3ha"] or 0.0)
            desvio = (real - t["propuesto_m3ha"]) / t["propuesto_m3ha"] * 100
            if abs(desvio) <= umbral:
                continue
            severidad = "alta" if abs(desvio) > 2 * umbral else "media"
            sentido = "más" if desvio > 0 else "menos"
            salida.append(_alerta(
                "desvio_plan_real", severidad, f"{t['turno_codigo']}: se regó {abs(desvio):.0f} % {sentido} de lo propuesto",
                f"Propuesto {t['propuesto_m3ha']:.1f} m³/ha ({t['propuesto_m3']:.0f} m³); aplicado {real:.1f} m³/ha "
                f"({(t['aplicado_m3'] or 0):.0f} m³).",
                fecha=dia["fecha"], turno_codigo=t["turno_codigo"], propuesto_m3ha=t["propuesto_m3ha"],
                aplicado_m3ha=_r(real, 2), propuesto_m3=t["propuesto_m3"], aplicado_m3=t["aplicado_m3"],
                desvio_pct=_r(desvio, 0)))
        return salida
    return []


def _racha(dias: list[AmbienteDiario], condicion) -> list[AmbienteDiario]:
    """Días seguidos que cumplen ``condicion``, contando hacia atrás desde el último con dato."""
    racha = []
    anterior: dt.date | None = None
    for a in reversed(dias):
        if anterior is not None and (anterior - a.fecha).days != 1:
            break
        if not condicion(a):
            break
        racha.append(a)
        anterior = a.fecha
    return list(reversed(racha))


def _alertas_estres(ambiente: list[AmbienteDiario], ayer: dt.date) -> list[dict[str, Any]]:
    salida = []
    minimo = settings.copiloto_dias_estres
    recientes = [a for a in ambiente if (ayer - a.fecha).days < DIAS_BUSCAR_DATO]
    con_mds = [a for a in ambiente if a.mds_contraccion_um is not None]
    if recientes and con_mds and con_mds[-1] in recientes:
        racha = _racha(con_mds, lambda a: a.mds_contraccion_um >= settings.copiloto_mds_alto_um)
        if len(racha) >= minimo:
            ultimo = racha[-1].mds_contraccion_um
            critico = ultimo >= settings.copiloto_mds_critico_um
            salida.append(_alerta(
                "estres_mds", "alta" if critico else "media",
                f"Estrés {'crítico' if critico else 'alto'} por MDS {len(racha)} días seguidos",
                f"MDS de {', '.join(f'{a.mds_contraccion_um:.0f}' for a in racha)} µm "
                f"(umbral alto {settings.copiloto_mds_alto_um:.0f} µm, crítico {settings.copiloto_mds_critico_um:.0f} µm).",
                fecha=racha[-1].fecha, dias=len(racha), mds_um=_r(ultimo, 0), nivel=nivel_mds(ultimo)))
    margen = settings.copiloto_margen_estres_suelo
    con_suelo = [a for a in ambiente
                 if a.hum_zona_radicular_cierre is not None and a.hum_linea_estres_cierre is not None]
    if recientes and con_suelo and con_suelo[-1] in recientes:
        racha = _racha(con_suelo, lambda a: a.hum_linea_estres_cierre - a.hum_zona_radicular_cierre >= margen)
        if len(racha) >= minimo:
            ultimo = racha[-1]
            salida.append(_alerta(
                "estres_suelo", "alta" if len(racha) >= 2 * minimo else "media",
                f"Zona radicular bajo la línea de estrés {len(racha)} días seguidos",
                f"Al cierre del {_f(ultimo.fecha)}: {ultimo.hum_zona_radicular_cierre:.2f} % vol. frente a la "
                f"línea de estrés de {ultimo.hum_linea_estres_cierre:.2f} % vol.",
                fecha=ultimo.fecha, dias=len(racha), humedad=_r(ultimo.hum_zona_radicular_cierre, 2),
                linea_estres=_r(ultimo.hum_linea_estres_cierre, 2)))
    return salida


def _riego_por_dia(db: Session, modulo: Modulo, desde: dt.date, hasta: dt.date) -> dict[dt.date, float]:
    """m³/ha del módulo por día (riego vigente aplicado o provisional)."""
    area = sum(t.area_ha for t in repo_riego.turnos_de_modulo(db, modulo.id) if t.activo) or modulo.area_ha
    m3: dict[dt.date, float] = {}
    for r in repo_riego.vigentes(db, modulo.id, desde=desde, hasta=hasta + dt.timedelta(days=1)):
        m3[r.fecha] = m3.get(r.fecha, 0.0) + sum(c.riego_m3 or 0 for c in r.ciclos)
    return {f: v / area for f, v in m3.items()} if area else {}


def _alertas_suelo(db: Session, modulo: Modulo, ayer: dt.date) -> list[dict[str, Any]]:
    desde = ayer - dt.timedelta(days=DIAS_MEDIANA_SUELO + DIAS_BUSCAR_DATO)
    humedad = repo.humedad_diaria(db, settings.phytech_project_id, desde, ayer)
    subidas = {f: h["maximo"] - h["inicio"] for f, h in humedad.items()
               if h["inicio"] is not None and h["maximo"] is not None and h["lecturas"] >= 18}
    if not subidas:
        return []
    riego = _riego_por_dia(db, modulo, desde, ayer)
    dia = max(subidas)
    if (ayer - dia).days >= DIAS_BUSCAR_DATO:
        return []
    referencia = [s for f, s in subidas.items() if f < dia and riego.get(f, 0) >= RIEGO_MINIMO_M3HA]
    if len(referencia) < 5:
        return []
    mediana = statistics.median(referencia)
    subida, regado = subidas[dia], riego.get(dia)
    if regado is not None and regado >= RIEGO_MINIMO_M3HA:
        limite = max(SUBIDA_MINIMA_SIN_RESPUESTA, FRACCION_SIN_RESPUESTA * mediana)
        if subida < limite:
            return [_alerta(
                "riego_sin_respuesta", "alta", "Se regó, pero el suelo casi no respondió",
                f"El {_f(dia)} se aplicaron {regado:.1f} m³/ha y la humedad de la zona radicular solo subió "
                f"{subida:.2f} % vol. (lo normal es ~{mediana:.1f} % vol.). Revisar goteros, válvulas o fugas cerca de "
                f"la sonda.", fecha=dia, aplicado_m3ha=_r(regado, 2), subida_pct_vol=_r(subida, 2),
                subida_normal_pct_vol=_r(mediana, 2))]
    elif regado is None or regado <= SIN_RIEGO_MAXIMO_M3HA:
        limite = max(SUBIDA_MINIMA_SIN_RIEGO, FRACCION_SIN_RIEGO * mediana)
        if subida >= limite:
            return [_alerta(
                "humedad_sin_riego", "media", "El suelo se humedeció sin riego registrado",
                f"El {_f(dia)} la humedad de la zona radicular subió {subida:.2f} % vol. (como un día de riego, "
                f"~{mediana:.1f} % vol.), pero no hay riego registrado. ¿Falta cargar el riego de ese día?",
                fecha=dia, aplicado_m3ha=_r(regado or 0.0, 2), subida_pct_vol=_r(subida, 2),
                subida_normal_pct_vol=_r(mediana, 2))]
    return []


def _alertas_pronostico(ambiente: list[AmbienteDiario], pron: dict[str, Any]) -> list[dict[str, Any]]:
    etos = [a.eto_mm for a in ambiente[-DIAS_CONTEXTO:] if a.eto_mm is not None]
    futuros = [p for p in pron["dias"] if p["eto_mm"] is not None]
    if len(etos) < 3 or not futuros:
        return []
    media = sum(etos) / len(etos)
    pico = max(futuros, key=lambda p: p["eto_mm"])
    if pico["eto_mm"] >= max(ETO_MINIMA_DEMANDA_ALTA, FACTOR_DEMANDA_ALTA * media):
        return [_alerta(
            "demanda_alta", "info", "Se viene más demanda de agua",
            f"El pronóstico de Phytech da {pico['eto_mm']:.1f} mm de ETo el {_f(pico['fecha'])}, frente a "
            f"{media:.1f} mm de media en la última semana.", fecha=pico["fecha"], eto_mm=pico["eto_mm"],
            eto_media_semana_mm=_r(media, 2))]
    return []


ORDEN_SEVERIDAD = {s: i for i, s in enumerate(SEVERIDADES)}


def alertas(db: Session, modulo: Modulo, fecha: dt.date, lector: Lector) -> list[dict[str, Any]]:
    return resumen(db, modulo, fecha, lector)["alertas"]


# --- Resumen diario -----------------------------------------------------------------


def resumen(db: Session, modulo: Modulo, fecha: dt.date | None, lector: Lector) -> dict[str, Any]:
    """Todo lo que el agente necesita para el informe de la mañana, ya calculado."""
    datos_service.validar_fechas(fecha)
    fecha = fecha or hoy_lima()
    ayer, manana = fecha - dt.timedelta(days=1), fecha + dt.timedelta(days=1)
    turnos = repo_riego.turnos_de_modulo(db, modulo.id)
    crono_hoy, crono_manana = repo_crono.por_fecha(db, modulo.id, fecha), repo_crono.por_fecha(db, modulo.id, manana)
    plan_hoy = plan_del_dia(db, modulo, fecha, turnos)
    plan_manana = plan_del_dia(db, modulo, manana, turnos)
    ambiente = repo_series.ambiente(db, modulo.fundo_id, ayer - dt.timedelta(days=DIAS_MEDIANA_SUELO), ayer)
    agua_reciente = agua(db, modulo, ayer - dt.timedelta(days=DIAS_BUSCAR_DATO - 1), ayer, lector)
    pron = pronostico(db, fecha)

    lista = [
        *_alertas_plan(crono_hoy, plan_hoy, fecha, es_hoy=True),
        *_alertas_plan(crono_manana, plan_manana, manana, es_hoy=False),
        *_alertas_frescura(db, modulo, fecha),
        *_alertas_desvio(agua_reciente["dias"]),
        *_alertas_estres(ambiente, ayer),
        *_alertas_suelo(db, modulo, ayer),
        *_alertas_pronostico(ambiente, pron),
    ]
    lista.sort(key=lambda a: ORDEN_SEVERIDAD[a["severidad"]])

    ultimo = next((a for a in reversed(ambiente) if a.eto_mm is not None or a.mds_contraccion_um is not None), None)
    semana = [a.eto_mm for a in ambiente[-DIAS_CONTEXTO:] if a.eto_mm is not None]
    dia_agua = agua_reciente["dias"][-1] if agua_reciente["dias"] else None
    return {
        "modulo": {"id": modulo.id, "codigo": modulo.codigo, "nombre": modulo.nombre, "area_ha": _r(modulo.area_ha, 2),
                   "turnos": [t.codigo for t in turnos if t.activo]},
        "fecha": fecha,
        "generado_at": ahora_lima().isoformat(timespec="seconds"),
        "plan_hoy": plan_hoy,
        "plan_manana": plan_manana,
        "ayer": {
            "fecha": ayer,
            "agua": {"turnos": dia_agua["turnos"] if dia_agua else [],
                     "totales": agua(db, modulo, ayer, ayer, lector)["totales"]},
        },
        "contexto": {
            "ultimo_dia_con_datos": _fila_clima(ultimo) if ultimo else None,
            "eto_media_semana_mm": _r(sum(semana) / len(semana), 2) if semana else None,
            "ultimos_dias": [_fila_clima(a) for a in ambiente[-DIAS_CONTEXTO:]],
        },
        "pronostico": pron,
        "alertas": lista,
        "conteo_alertas": {s: sum(1 for a in lista if a["severidad"] == s) for s in SEVERIDADES},
        "sugerencias_pendientes": repo.contar_pendientes(db, modulo.id),
        "umbrales": umbrales(),
        "unidades": {"agua": "m³ y m³/ha", "eto": "mm", "mds": "µm", "humedad_suelo": "% vol."},
    }
