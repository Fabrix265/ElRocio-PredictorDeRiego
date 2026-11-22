"""Avisos del copiloto: lo que n8n manda solo por Telegram apenas pasa, sin esperar el informe diario.

| Código | Destino | Cuándo |
|---|---|---|
| ``mds_nivel`` | campo | El MDS del último día con dato cambió de nivel frente al día anterior con dato. Avisa al subir (estrés moderado, alto o crítico) y al bajar. Los umbrales son ``COPILOTO_MDS_*``, los del semáforo de la app. |
| ``ingesta_fallida`` | sistema | Pasados ``COPILOTO_GRACIA_INGESTA_MIN`` minutos de ``INGESTA_HORA``, una fuente de la ingesta programada de hoy terminó en error o incompleta, o no corrió. También si corrió bien pero sus datos no llegan a ayer (clima y Phytech), o el riego registrado tiene 2 o más días de atraso. |
| ``riego_sin_respuesta`` | campo | Se regó, pero la humedad de la zona radicular casi no subió: posible gotero tapado, válvula o fuga. Es la misma regla del resumen. |
| ``cronograma`` | cronogramas | En las últimas :data:`VENTANA_EVENTOS_H` horas se generó, regeneró, corrigió, publicó, modificó, anuló o descartó un cronograma, o se pidió o mantuvo una corrección. Trae el plan de la versión por turno y ciclo (m³, m³/ha, horario y ETo), la diferencia con la versión anterior, quién lo hizo y el enlace a la app. Una generación de varios días es un solo aviso. |

Cada aviso tiene una ``clave`` estable (``código:módulo:fecha:detalle``). n8n pide los pendientes, los
manda y confirma las claves enviadas. La confirmación queda en la auditoría (``aviso_enviado``) y ese
aviso ya no vuelve a salir como pendiente. Si Telegram falla, n8n no confirma y el aviso se reintenta
en la siguiente consulta.

Solo lectura salvo la confirmación, que nunca toca cronogramas, riego ni datos.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import DatosInvalidos
from app.core.tiempo import a_lima, ahora_lima
from app.models import Cronograma, CronogramaEvento, Modulo, TokenServicio, Usuario
from app.models.enums import EstadoIngesta, TipoEventoCronograma
from app.repositories import copiloto as repo
from app.repositories import cronogramas as repo_crono
from app.repositories import datos_series as repo_series
from app.repositories import riego as repo_riego
from app.services import agente_service, auditoria_service, datos_service, ingesta_service
from app.services.contexto import ContextoPeticion
from app.services.copiloto_service import (
    DIAS_BUSCAR_DATO,
    ETIQUETA_ESTADO,
    ORDEN_SEVERIDAD,
    _alertas_suelo,
    nivel_mds,
    plan_de_version,
)

CODIGOS = ("mds_nivel", "ingesta_fallida", "riego_sin_respuesta", "cronograma")  # los de PATRON_CLAVE_AVISO
DIAS_MDS = 10
ORDEN_NIVEL = {"sin_estres": 0, "moderado": 1, "alto": 2, "critico": 3}
NOMBRE_NIVEL = {"sin_estres": "sin estrés", "moderado": "estrés moderado", "alto": "estrés alto",
                "critico": "estrés crítico"}
ICONO_NIVEL = {"sin_estres": "🟢", "moderado": "🟡", "alto": "🟠", "critico": "🔴"}
NOMBRE_FUENTE = {
    ingesta_service.WEATHERLINK: "WeatherLink (clima)",
    ingesta_service.PHYTECH_SUELO: "Phytech suelo",
    ingesta_service.PHYTECH_PLANTA: "Phytech planta (MDS)",
    ingesta_service.NDVI: "NDVI",
    ingesta_service.PRONOSTICO: "Pronóstico de Phytech",
    ingesta_service.GALILEO: "Riego del controlador (Galileo)",
}
# Fuente de la ingesta → fuente de la frescura de datos (las que alimentan el plan).
FRESCURA_DE = {
    ingesta_service.WEATHERLINK: "weatherlink",
    ingesta_service.PHYTECH_SUELO: "phytech_suelo",
    ingesta_service.PHYTECH_PLANTA: "phytech_planta",
    ingesta_service.GALILEO: "riego_provisional",
}
# Días de atraso que se toleran sin avisar (el controlador puede completar el riego de ayer más tarde).
ATRASO_TOLERADO = {"riego_provisional": 1}
FUENTES_INFORMATIVAS = {ingesta_service.NDVI, ingesta_service.PRONOSTICO}


def _f(fecha: dt.date) -> str:
    return fecha.strftime("%d/%m/%Y")


def _n(valor: float, decimales: int = 1) -> str:
    """Número como lo muestra la app (es-PE): miles con coma y decimales con punto, p. ej. 3,812.5."""
    return f"{valor:,.{decimales}f}"


def _aviso(codigo: str, modulo: Modulo, fecha: dt.date, detalle_clave: str, *, severidad: str, destino: str,
           icono: str, titulo: str, detalle: str, resumen: str | None = None, ruta: str | None = None,
           **valores: Any) -> dict[str, Any]:
    """``detalle`` es el texto completo del mensaje; ``resumen``, una línea para listados (``/avisos``);
    ``ruta``, la pantalla de la app que lo muestra (relativa)."""
    return {"clave": f"{codigo}:{modulo.id}:{fecha.isoformat()}:{detalle_clave}", "codigo": codigo,
            "severidad": severidad, "destino": destino, "icono": icono, "titulo": titulo, "detalle": detalle,
            "resumen": resumen or detalle, "ruta": ruta, "fecha": fecha, "valores": valores}


# --- 1. Cambio de nivel del MDS ---------------------------------------------------------


def _aviso_mds(db: Session, modulo: Modulo, ayer: dt.date) -> list[dict[str, Any]]:
    filas = [a for a in repo_series.ambiente(db, modulo.fundo_id, ayer - dt.timedelta(days=DIAS_MDS), ayer)
             if a.mds_contraccion_um is not None]
    if len(filas) < 2:
        return []
    ultimo, previo = filas[-1], filas[-2]
    if (ayer - ultimo.fecha).days >= DIAS_BUSCAR_DATO or (ultimo.fecha - previo.fecha).days > DIAS_BUSCAR_DATO:
        return []
    nivel, antes = nivel_mds(ultimo.mds_contraccion_um), nivel_mds(previo.mds_contraccion_um)
    if nivel == antes:
        return []
    sube = ORDEN_NIVEL[nivel] > ORDEN_NIVEL[antes]
    severidad = {"critico": "alta", "alto": "media"}.get(nivel, "info") if sube else "info"
    eto = f", con ETo de {_n(ultimo.eto_mm)} mm" if ultimo.eto_mm is not None else ""
    consejo = " Revisa que el plan de hoy cubra la demanda." if sube and nivel in ("alto", "critico") else ""
    return [_aviso(
        "mds_nivel", modulo, ultimo.fecha, nivel, severidad=severidad, destino="campo", icono=ICONO_NIVEL[nivel],
        titulo=f"El MDS {'subió' if sube else 'bajó'} a {NOMBRE_NIVEL[nivel]}",
        detalle=(f"El {_f(ultimo.fecha)} el MDS fue de {_n(ultimo.mds_contraccion_um, 0)} µm{eto}. El "
                 f"{_f(previo.fecha)} fue de {_n(previo.mds_contraccion_um, 0)} µm ({NOMBRE_NIVEL[antes]}). Niveles: "
                 f"moderado desde {_n(settings.copiloto_mds_moderado_um, 0)}, alto desde "
                 f"{_n(settings.copiloto_mds_alto_um, 0)} y crítico desde {_n(settings.copiloto_mds_critico_um, 0)} µm."
                 f"{consejo}"),
        nivel=nivel, nivel_anterior=antes, sube=sube, mds_um=round(ultimo.mds_contraccion_um),
        mds_anterior_um=round(previo.mds_contraccion_um), fecha_anterior=previo.fecha,
        eto_mm=None if ultimo.eto_mm is None else round(ultimo.eto_mm, 2),
    )]


# --- 2. Ingesta programada que falló -----------------------------------------------------


def _ya_paso_la_gracia(ahora: dt.datetime) -> bool:
    hora, minuto = (int(p) for p in settings.ingesta_hora.split(":"))
    return ahora.hour * 60 + ahora.minute >= hora * 60 + minuto + settings.copiloto_gracia_ingesta_min


def _primer_error(errores: list[dict[str, Any]] | None) -> str:
    for error in errores or []:
        mensaje = str(error.get("mensaje") or error.get("tipo") or "").strip()
        if mensaje:
            return f" Error: {mensaje[:160]}."
    return ""


def _avisos_ingesta(db: Session, modulo: Modulo, hoy: dt.date, ahora: dt.datetime) -> list[dict[str, Any]]:
    if not _ya_paso_la_gracia(ahora):
        return []
    corridas = {c.fuente: c for c in repo.corridas_programadas(db, hoy)}
    frescura = datos_service.frescura(db, modulo.id, hoy)
    por_fuente = {f.fuente: f for f in frescura.fuentes}
    hora = settings.ingesta_hora
    salida = []
    for fuente in ingesta_service.FUENTES:
        nombre = NOMBRE_FUENTE.get(fuente, fuente)
        corrida = corridas.get(fuente)

        def aviso(severidad: str, titulo: str, detalle: str, *, fuente: str = fuente, **valores: Any) -> None:
            salida.append(_aviso(
                "ingesta_fallida", modulo, hoy, fuente, severidad=severidad, destino="sistema",
                icono="🔴" if severidad == "alta" else "🟠", titulo=titulo, detalle=detalle, fuente=fuente,
                **valores))

        if corrida is None:
            # Sin programador (p. ej. ingesta por cron con la CLI) no hay corrida programada que esperar.
            if settings.scheduler_enabled:
                aviso("media" if fuente in FUENTES_INFORMATIVAS else "alta",
                      f"La ingesta de {nombre} no corrió hoy",
                      f"La ingesta programada de las {hora} no se ejecutó. Revisa que la API esté corriendo y usa "
                      f"«Actualizar ahora» en la pantalla Datos.", estado=None)
            continue
        if corrida.estado == EstadoIngesta.en_curso:
            continue
        if corrida.estado in (EstadoIngesta.error, EstadoIngesta.parcial):
            fallo = corrida.estado == EstadoIngesta.error
            aviso("alta" if fallo and fuente not in FUENTES_INFORMATIVAS else "media",
                  f"La ingesta de {nombre} {'falló' if fallo else 'quedó incompleta'}",
                  f"La ingesta programada de las {hora} terminó {'en error' if fallo else 'con datos incompletos'}."
                  f"{_primer_error(corrida.errores)} Hasta que se corrija, el plan usaría datos viejos. Usa "
                  f"«Actualizar ahora» en la pantalla Datos.", estado=corrida.estado.value)
            continue
        dato = por_fuente.get(FRESCURA_DE.get(fuente, ""))
        if dato is None or dato.estado != "naranja":
            continue
        atraso = None if dato.ultima_fecha is None else (frescura.referencia - dato.ultima_fecha).days
        if atraso is not None and atraso <= ATRASO_TOLERADO.get(dato.fuente, 0):
            continue
        ultimo = "no hay ningún dato" if dato.ultima_fecha is None else (
            f"el último dato es del {_f(dato.ultima_fecha)} ({atraso} día(s) de atraso respecto de "
            f"{_f(frescura.referencia)})")
        aviso("media", f"{nombre}: la ingesta corrió, pero faltan datos",
              f"La ingesta de las {hora} terminó sin errores, pero {ultimo}. Si se genera un plan ahora, usaría "
              f"datos viejos.", estado=corrida.estado.value, ultima_fecha=dato.ultima_fecha, dias_atraso=atraso)
    return salida


# --- 3. Riego sin respuesta del suelo ----------------------------------------------------


def _aviso_riego(db: Session, modulo: Modulo, ayer: dt.date) -> list[dict[str, Any]]:
    alerta = next((a for a in _alertas_suelo(db, modulo, ayer) if a["codigo"] == "riego_sin_respuesta"), None)
    if alerta is None:
        return []
    v, fecha = alerta["valores"], alerta["fecha"]
    area = sum(t.area_ha for t in repo_riego.turnos_de_modulo(db, modulo.id) if t.activo) or modulo.area_ha
    m3 = v["aplicado_m3ha"] * area if area else None
    dia = next((a for a in repo_series.ambiente(db, modulo.fundo_id, fecha, fecha)), None)
    eto = None if dia is None or dia.eto_mm is None else dia.eto_mm
    agua = f"{_n(m3, 0)} m³ ({_n(v['aplicado_m3ha'])} m³/ha)" if m3 is not None else f"{_n(v['aplicado_m3ha'])} m³/ha"
    return [_aviso(
        "riego_sin_respuesta", modulo, fecha, "suelo", severidad="alta", destino="campo", icono="🔴",
        titulo="Posible falla de riego: el suelo no respondió",
        detalle=(f"El {_f(fecha)} se regaron {agua}{f' con ETo de {_n(eto)} mm' if eto is not None else ''}, pero la "
                 f"humedad de la zona radicular solo subió {_n(v['subida_pct_vol'], 2)} % vol. (lo normal es "
                 f"~{_n(v['subida_normal_pct_vol'])} % vol.). Revisa goteros, válvulas o fugas cerca de la sonda de "
                 f"Phytech."),
        aplicado_m3=None if m3 is None else round(m3, 1), eto_mm=None if eto is None else round(eto, 2), **v,
    )]


# --- 4. Cambios en los cronogramas -------------------------------------------------------

VENTANA_EVENTOS_H = 12
LIMITE_TEXTO = 3700  # título + detalle + enlace caben en los 4096 caracteres de Telegram
DIAS_SEMANA = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
EVENTOS_GENERACION = (TipoEventoCronograma.generado, TipoEventoCronograma.regenerado)
# tipo → (ícono, título, severidad, verbo). correccion_atendida no avisa: la sigue «modificado».
EVENTOS = {
    TipoEventoCronograma.corregido: ("✏️", "Plan de riego corregido", "info", "Lo corrigió"),
    TipoEventoCronograma.publicado: ("✅", "Plan de riego publicado", "info", "Lo publicó"),
    TipoEventoCronograma.modificado: ("✅", "Cambios publicados en el plan de riego", "info", "Publicó los cambios"),
    TipoEventoCronograma.borrador_descartado: ("↩️", "Se descartó un borrador del plan de riego", "info",
                                               "Lo descartó"),
    TipoEventoCronograma.correccion_solicitada: ("⚠️", "Piden corregir el plan de riego", "media", "Lo pidió"),
    TipoEventoCronograma.correccion_mantenida: ("📌", "Se mantiene el plan de riego sin cambios", "info",
                                                "Lo decidió"),
    TipoEventoCronograma.anulado: ("🗑️", "Plan de riego anulado", "media", "Lo anuló"),
}
EVENTOS_AVISO = (*EVENTOS_GENERACION, *EVENTOS)
NOMBRE_ROL = {"admin": "administrador", "encargado": "encargado", "subgerente": "subgerente",
              "programador": "programador"}
NOMBRE_ORIGEN = {"modelo": "del modelo", "regenerado": "regenerada con el modelo", "correccion": "corregida",
                 "edicion": "editada"}


def _dia(fecha: dt.date, *, anio: bool = True) -> str:
    return f"{DIAS_SEMANA[fecha.weekday()]} {fecha.strftime('%d/%m/%Y' if anio else '%d/%m')}"


def _quien(usuario: Usuario | None) -> str:
    if usuario is None:
        return "el sistema"
    rol = NOMBRE_ROL.get(getattr(usuario.rol, "value", str(usuario.rol)))
    return f"{usuario.nombre} ({rol})" if rol else usuario.nombre


def _cuando(instante: dt.datetime) -> str:
    local = a_lima(instante)
    return f"el {local.strftime('%d/%m/%Y')} a las {local.strftime('%H:%M')}"


def _agua(m3: float | None, m3ha: float | None) -> str:
    if m3 is None:
        return "sin dato"
    return f"{_n(m3, 0)} m³ · {_n(m3ha, 1)} m³/ha" if m3ha is not None else f"{_n(m3, 0)} m³"


def _cambio(actual: float | None, antes: float | None) -> str:
    if actual is None or not antes:
        return ""
    pct = (actual - antes) / antes * 100
    return f", {pct:+.1f} %"


def _horario(turno: dict[str, Any]) -> str:
    if not turno["ciclos"]:
        return "sin riego"
    ultimo = turno["ciclos"][-1]
    return f"{turno['inicio']}–{turno['fin']}{' (+1 día)' if ultimo['fin_dia_siguiente'] else ''}"


def _firma(turno: dict[str, Any]) -> tuple:
    return tuple((c["hora_inicio"], c["hora_fin"], c["m3"]) for c in turno["ciclos"])


def _linea_version(plan: dict[str, Any], crono: Cronograma, version: Any | None) -> str:
    if plan["version"] is None:
        return "Sin versión."
    partes = [f"Versión {plan['version']} ({NOMBRE_ORIGEN.get(plan['origen_version'], plan['origen_version'])})",
              "anulado" if crono.anulado_at else f"estado actual: {ETIQUETA_ESTADO.get(crono.estado, crono.estado.value)}"]
    if version is not None and version.preliminar:
        partes.append("preliminar")
    if version is not None and version.datos_incompletos:
        partes.append("calculado con datos incompletos")
    return " · ".join(partes)


def _lineas_plan(plan: dict[str, Any], anterior: dict[str, Any] | None = None, *, ciclos: bool = True) -> list[str]:
    """El plan por turno (y ciclo) con m³, m³/ha, horario y ETo; con ``anterior``, lo que cambió."""
    lineas = []
    eto = []
    if plan["eto_dia_anterior_mm"] is not None:
        eto.append(f"ETo del día anterior: {_n(plan['eto_dia_anterior_mm'])} mm"
                   f"{' (pronóstico)' if plan['eto_dia_anterior_es_pronostico'] else ''}")
    if plan["eto_pronostico_mm"] is not None:
        eto.append(f"ETo pronosticada del día: {_n(plan['eto_pronostico_mm'])} mm")
    if eto:
        lineas.append(" · ".join(eto))
    if plan["total_m3"] is None:
        return [*lineas, "Esta versión no tiene ciclos de riego."]
    total = f"Total: {_agua(plan['total_m3'], plan['total_m3ha'])}"
    if anterior is not None and anterior.get("total_m3") is not None:
        if round(anterior["total_m3"]) == round(plan["total_m3"]):
            total += " (sin cambios frente a la versión anterior)"
        else:
            total += (f" (antes: {_agua(anterior['total_m3'], anterior['total_m3ha'])}"
                      f"{_cambio(plan['total_m3'], anterior['total_m3'])})")
    lineas.append(total)
    previos = {t["turno_codigo"]: t for t in (anterior or {}).get("turnos", [])}
    cambiados = [t["turno_codigo"] for t in plan["turnos"]
                 if t["turno_codigo"] in previos and _firma(t) != _firma(previos[t["turno_codigo"]])]
    if anterior is not None:
        lineas.append(f"Turnos que cambiaron: {', '.join(cambiados)}" if cambiados else "Ningún turno cambió.")
    lineas.append("Por turno:")
    for t in plan["turnos"]:
        if not t["n_ciclos"]:
            linea = f"• {t['turno_codigo']} ({_n(t['area_ha'], 2)} ha): sin riego"
        else:
            linea = (f"• {t['turno_codigo']} ({_n(t['area_ha'], 2)} ha) · {t['n_ciclos']} ciclo(s) · {_horario(t)}: "
                     f"{_agua(t['m3'], t['m3ha'])}")
        if t["turno_codigo"] in cambiados:
            p = previos[t["turno_codigo"]]
            linea += (f" (antes: {_agua(p['m3'], p['m3ha'])}, {p['n_ciclos']} ciclo(s), {_horario(p)}"
                      f"{_cambio(t['m3'], p['m3'])})")
        lineas.append(linea)
        if ciclos:
            for c in t["ciclos"]:
                fin = c["hora_fin"] + (" (+1 día)" if c["fin_dia_siguiente"] else "")
                lineas.append(f"   {c['ciclo']}) {c['hora_inicio']}–{fin} · {_n(c['m3'], 0)} m³ · {_n(c['m3ha'], 1)} m³/ha")
    return lineas


def _cerrar(lineas: list[str], enlace: str) -> str:
    texto = "\n".join(lineas).strip()
    if len(texto) > LIMITE_TEXTO:
        texto = texto[:texto.rfind("\n", 0, LIMITE_TEXTO)] + "\n… (el detalle completo está en la app)"
    return f"{texto}\n\n🔗 Ver en la app: {enlace}"


def _anterior(db: Session, crono: Cronograma, version: Any | None, tipo: TipoEventoCronograma) -> Any | None:
    """La versión con la que se compara: la base de una corrección, la publicada antes de publicar
    cambios, o la anterior de una regeneración."""
    if version is None:
        return None
    if tipo == TipoEventoCronograma.corregido and version.basada_en_id:
        return repo_crono.version(db, version.basada_en_id)
    previas = [v for v in repo_crono.versiones(db, crono.id) if v.numero < version.numero]
    if tipo == TipoEventoCronograma.modificado:
        previas = [v for v in previas if v.publicada_at is not None] or previas
    return max(previas, key=lambda v: v.numero, default=None)


def _resumen(fecha: dt.date, plan: dict[str, Any], usuario: Usuario | None) -> str:
    return (f"{_dia(fecha, anio=False)} · versión {plan['version']} · {_agua(plan['total_m3'], plan['total_m3ha'])}"
            f" · por {_quien(usuario)}")


def _aviso_generacion(db: Session, modulo: Modulo, clave: str, grupo: list[tuple[CronogramaEvento, Cronograma]],
                      turnos: list[Any], usuarios: dict[int, Usuario], base: str) -> dict[str, Any]:
    grupo = sorted(grupo, key=lambda par: par[1].fecha)
    primero = grupo[0][0]
    usuario = usuarios.get(primero.usuario_id) if primero.usuario_id else None
    planes = []
    for evento, crono in grupo:
        version = repo_crono.version(db, evento.version_id)
        planes.append((evento, crono, version, plan_de_version(db, modulo, crono, version, turnos)))
    fechas = [crono.fecha for _e, crono, _v, _p in planes]
    regenerados = sum(1 for e, *_ in planes if e.tipo == TipoEventoCronograma.regenerado)
    if len(planes) == 1:
        evento, crono, version, plan = planes[0]
        regenera = evento.tipo == TipoEventoCronograma.regenerado
        anterior = _anterior(db, crono, version, evento.tipo) if regenera else None
        plan_anterior = plan_de_version(db, modulo, crono, anterior, turnos) if anterior is not None else None
        icono, titulo = ("🔄", "Plan de riego regenerado") if regenera else ("📋", "Plan de riego generado")
        titulo += f" · {_dia(crono.fecha, anio=False)}"
        lineas = [f"Plan del {_dia(crono.fecha)} · {modulo.nombre}",
                  f"Lo {'regeneró' if regenera else 'generó'} {_quien(usuario)} {_cuando(evento.ocurrido_at)}.",
                  _linea_version(plan, crono, version), "", *_lineas_plan(plan, plan_anterior)]
        ruta, resumen = f"/cronogramas/{crono.id}", _resumen(crono.fecha, plan, usuario)
    else:
        icono = "📋"
        verbo = "regeneraron" if regenerados == len(planes) else "generaron"
        titulo = f"Se {verbo} {len(planes)} planes de riego · del {fechas[0]:%d/%m} al {fechas[-1]:%d/%m}"
        lineas = [f"{modulo.nombre} · {len(planes)} días",
                  f"Los generó {_quien(usuario)} {_cuando(primero.ocurrido_at)}.", ""]
        for evento, crono, version, plan in planes:
            regenera = " (regenerado)" if evento.tipo == TipoEventoCronograma.regenerado else ""
            eto = f" · ETo {_n(plan['eto_pronostico_mm'])} mm" if plan["eto_pronostico_mm"] is not None else ""
            lineas.append(f"• {_dia(crono.fecha, anio=False)} · versión {plan['version']}{regenera} · "
                          f"{_agua(plan['total_m3'], plan['total_m3ha'])}{eto}")
            for t in plan["turnos"]:
                lineas.append(f"   {t['turno_codigo']}: {_agua(t['m3'], t['m3ha'])} · {_horario(t)} "
                              f"({t['n_ciclos']} ciclo(s))" if t["n_ciclos"] else f"   {t['turno_codigo']}: sin riego")
        lineas += ["", "Para ver los ciclos de un día, escribe /plan DD/MM al bot."]
        ruta = "/cronogramas"
        resumen = f"{len(planes)} días, del {fechas[0]:%d/%m} al {fechas[-1]:%d/%m} · por {_quien(usuario)}"
    return _aviso("cronograma", modulo, fechas[0], clave, severidad="info", destino="cronogramas", icono=icono,
                  titulo=titulo, detalle=_cerrar(lineas, base + ruta), resumen=resumen, ruta=ruta,
                  evento="generacion", fechas=fechas, cronograma_ids=[c.id for _e, c, _v, _p in planes],
                  ocurrido_at=primero.ocurrido_at)


def _aviso_evento(db: Session, modulo: Modulo, evento: CronogramaEvento, crono: Cronograma, turnos: list[Any],
                  usuarios: dict[int, Usuario], motivos: dict[str, str], base: str) -> dict[str, Any]:
    icono, titulo, severidad, verbo = EVENTOS[evento.tipo]
    tipo = evento.tipo
    usuario = usuarios.get(evento.usuario_id) if evento.usuario_id else None
    version = repo_crono.version(db, evento.version_id)
    extra: list[str] = []
    if tipo == TipoEventoCronograma.borrador_descartado:
        # Se muestra lo que sigue vigente: la versión publicada.
        descartada = version.numero if version is not None else None
        version = repo_crono.version(db, crono.version_publicada_id)
        extra.append(f"Se descartó la versión {descartada}; sigue vigente la publicada."
                     if descartada else "Sigue vigente la versión publicada.")
    plan = plan_de_version(db, modulo, crono, version, turnos)
    anterior = None
    if tipo in (TipoEventoCronograma.corregido, TipoEventoCronograma.modificado):
        previa = _anterior(db, crono, version, tipo)
        anterior = plan_de_version(db, modulo, crono, previa, turnos) if previa is not None else None
    if tipo == TipoEventoCronograma.corregido and (evento.motivo_codigo or evento.comentario):
        motivo = motivos.get(evento.motivo_codigo or "", evento.motivo_codigo or "")
        extra.append("Motivo: " + " — ".join(p for p in (motivo, evento.comentario) if p))
    elif tipo == TipoEventoCronograma.publicado:
        extra.append("El programador ya puede verlo.")
    elif tipo == TipoEventoCronograma.modificado:
        extra.append("Es la corrección de un día pasado." if (evento.detalle or {}).get("retrospectiva")
                     else "El programador ya ve la nueva versión.")
    elif tipo in (TipoEventoCronograma.correccion_solicitada, TipoEventoCronograma.anulado) and evento.comentario:
        extra.append(f"Motivo: {evento.comentario}")
    elif tipo == TipoEventoCronograma.correccion_mantenida and evento.comentario:
        extra.append(f"Comentario: {evento.comentario}")
    lineas = [f"Plan del {_dia(crono.fecha)} · {modulo.nombre}",
              f"{verbo} {_quien(usuario)} {_cuando(evento.ocurrido_at)}.", *extra,
              _linea_version(plan, crono, version), "",
              *_lineas_plan(plan, anterior, ciclos=tipo != TipoEventoCronograma.anulado)]
    ruta = f"/cronogramas/{crono.id}"
    resumen = _resumen(crono.fecha, plan, usuario)
    if tipo in (TipoEventoCronograma.correccion_solicitada, TipoEventoCronograma.anulado) and evento.comentario:
        resumen += f" · motivo: {evento.comentario[:80]}"
    return _aviso("cronograma", modulo, crono.fecha, f"e{evento.id}", severidad=severidad, destino="cronogramas",
                  icono=icono, titulo=f"{titulo} · {_dia(crono.fecha, anio=False)}",
                  detalle=_cerrar(lineas, base + ruta), resumen=resumen, ruta=ruta, evento=tipo.value,
                  cronograma_id=crono.id, version=plan["version"], ocurrido_at=evento.ocurrido_at)


def _avisos_cronograma(db: Session, modulo: Modulo, ahora: dt.datetime) -> list[dict[str, Any]]:
    filas = repo.eventos_cronograma(db, modulo.id, ahora - dt.timedelta(hours=VENTANA_EVENTOS_H), EVENTOS_AVISO)
    if not filas:
        return []
    turnos = repo_riego.turnos_de_modulo(db, modulo.id)
    usuarios = repo.usuarios_por_id(db, {e.usuario_id for e, _c in filas if e.usuario_id})
    motivos = repo.nombres_motivo(db, {e.motivo_codigo for e, _c in filas if e.motivo_codigo})
    base = settings.frontend_url.rstrip("/")
    salida, generaciones = [], {}
    for evento, crono in filas:
        if evento.tipo in EVENTOS_GENERACION:
            # Una generación de varios días es un solo aviso.
            gid = (evento.detalle or {}).get("generacion_id")
            generaciones.setdefault(f"g{gid}" if gid is not None else f"e{evento.id}", []).append((evento, crono))
        else:
            salida.append(_aviso_evento(db, modulo, evento, crono, turnos, usuarios, motivos, base))
    salida += [_aviso_generacion(db, modulo, clave, grupo, turnos, usuarios, base)
               for clave, grupo in generaciones.items()]
    return sorted(salida, key=lambda a: a["valores"]["ocurrido_at"])


# --- /plan del bot -------------------------------------------------------------------------


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def interpretar_dia(texto: str, hoy: dt.date) -> dt.date:
    """«hoy», «mañana», «ayer», «pasado mañana», un día de la semana (el próximo, hoy incluido),
    «23/11», «23/11/2026» o «2026-11-23». Sin año, el más cercano a hoy."""
    t = _sin_tildes(texto.strip().lower())
    relativos = {"": 0, "hoy": 0, "manana": 1, "ayer": -1, "pasado manana": 2, "pasado": 2}
    if t in relativos:
        return hoy + dt.timedelta(days=relativos[t])
    semana = [_sin_tildes(d) for d in DIAS_SEMANA]
    if t in semana:
        return hoy + dt.timedelta(days=(semana.index(t) - hoy.weekday()) % 7)
    try:
        if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", t):
            return dt.date(int(m[1]), int(m[2]), int(m[3]))
        if m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?", t):
            dia, mes = int(m[1]), int(m[2])
            if m[3]:
                anio = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
                return dt.date(anio, mes, dia)
            candidatos = [dt.date(hoy.year + d, mes, dia) for d in (-1, 0, 1)]
            return min(candidatos, key=lambda f: abs((f - hoy).days))
    except ValueError:
        pass
    raise DatosInvalidos("No entendí la fecha. Usa hoy, mañana, un día de la semana, 23/11 o 23/11/2026.")


def plan_en_texto(db: Session, modulo: Modulo, dia: str) -> dict[str, Any]:
    """El plan completo de un día como texto para Telegram (lo que muestra ``/plan``)."""
    fecha = interpretar_dia(dia, ahora_lima().date())
    datos_service.validar_fechas(fecha)
    crono = repo_crono.por_fecha(db, modulo.id, fecha)
    if crono is None:
        return {"fecha": fecha, "hay_plan": False, "cronograma_id": None,
                "texto": f"No hay plan de riego para el {_dia(fecha)}. Se genera en la app, en la pantalla Generar."}
    version = repo_crono.version(db, crono.version_publicada_id or crono.borrador_version_id)
    plan = plan_de_version(db, modulo, crono, version)
    lineas = [f"📋 Plan de riego del {_dia(fecha)} · {modulo.nombre}", _linea_version(plan, crono, version), "",
              *_lineas_plan(plan)]
    return {"fecha": fecha, "hay_plan": True, "cronograma_id": crono.id,
            "texto": _cerrar(lineas, f"{settings.frontend_url.rstrip('/')}/cronogramas/{crono.id}")}


# --- Consulta y confirmación ---------------------------------------------------------------


def avisos(db: Session, modulo: Modulo, *, ahora: dt.datetime | None = None) -> list[dict[str, Any]]:
    """Los avisos de este momento, cada uno con ``enviado`` (si ya se confirmó su envío)."""
    ahora = ahora or ahora_lima()
    hoy = ahora.date()
    ayer = hoy - dt.timedelta(days=1)
    lista = [*_avisos_ingesta(db, modulo, hoy, ahora), *_aviso_mds(db, modulo, ayer), *_aviso_riego(db, modulo, ayer)]
    lista.sort(key=lambda a: ORDEN_SEVERIDAD[a["severidad"]])
    lista += _avisos_cronograma(db, modulo, ahora)  # en el orden en que pasaron
    enviados = repo.claves_avisadas(db, [a["clave"] for a in lista], accion=auditoria_service.AVISO_ENVIADO,
                                    entidad=auditoria_service.ENTIDAD_AVISO)
    for a in lista:
        a["enviado"] = a["clave"] in enviados
    return lista


def confirmar(db: Session, claves: list[str], *, token: TokenServicio, contexto: ContextoPeticion) -> dict[str, int]:
    """Deja en la auditoría las claves que n8n ya mandó por Telegram (las repetidas se ignoran)."""
    repo.bloquear_avisos(db)
    claves = list(dict.fromkeys(claves))
    ya = repo.claves_avisadas(db, claves, accion=auditoria_service.AVISO_ENVIADO,
                              entidad=auditoria_service.ENTIDAD_AVISO)
    nuevas = [c for c in claves if c not in ya]
    for clave in nuevas:
        codigo, modulo_id, fecha, detalle = clave.split(":")
        auditoria_service.registrar(
            db, accion=auditoria_service.AVISO_ENVIADO, entidad=auditoria_service.ENTIDAD_AVISO, entidad_id=clave,
            actor_username=agente_service.nombre_actor(token),
            detalle={"codigo": codigo, "modulo_id": int(modulo_id), "fecha": fecha, "detalle": detalle},
            contexto=contexto,
        )
    db.flush()
    return {"confirmadas": len(nuevas), "ya_confirmadas": len(claves) - len(nuevas)}
