"""Avisos del copiloto: lo que n8n manda solo por Telegram apenas pasa, sin esperar el informe diario.

| Código | Destino | Cuándo |
|---|---|---|
| ``mds_nivel`` | campo | El MDS del último día con dato cambió de nivel frente al día anterior con dato. Avisa al subir (estrés moderado, alto o crítico) y al bajar. Los umbrales son ``COPILOTO_MDS_*``, los del semáforo de la app. |
| ``ingesta_fallida`` | sistema | Pasados ``COPILOTO_GRACIA_INGESTA_MIN`` minutos de ``INGESTA_HORA``, una fuente de la ingesta programada de hoy terminó en error o incompleta, o no corrió. También si corrió bien pero sus datos no llegan a ayer (clima y Phytech), o el riego registrado tiene 2 o más días de atraso. |
| ``riego_sin_respuesta`` | campo | Se regó, pero la humedad de la zona radicular casi no subió: posible gotero tapado, válvula o fuga. Es la misma regla del resumen. |

Cada aviso tiene una ``clave`` estable (``código:módulo:fecha:detalle``). n8n pide los pendientes, los
manda y confirma las claves enviadas. La confirmación queda en la auditoría (``aviso_enviado``) y ese
aviso ya no vuelve a salir como pendiente. Si Telegram falla, n8n no confirma y el aviso se reintenta
en la siguiente consulta.

Solo lectura salvo la confirmación, que nunca toca cronogramas, riego ni datos.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.tiempo import ahora_lima
from app.models import Modulo, TokenServicio
from app.models.enums import EstadoIngesta
from app.repositories import copiloto as repo
from app.repositories import datos_series as repo_series
from app.repositories import riego as repo_riego
from app.services import agente_service, auditoria_service, datos_service, ingesta_service
from app.services.contexto import ContextoPeticion
from app.services.copiloto_service import DIAS_BUSCAR_DATO, ORDEN_SEVERIDAD, _alertas_suelo, nivel_mds

CODIGOS = ("mds_nivel", "ingesta_fallida", "riego_sin_respuesta")  # los de PATRON_CLAVE_AVISO
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
    """Número con coma decimal, como se lee en Perú (el texto va tal cual a Telegram)."""
    return f"{valor:.{decimales}f}".replace(".", ",")


def _aviso(codigo: str, modulo: Modulo, fecha: dt.date, detalle_clave: str, *, severidad: str, destino: str,
           icono: str, titulo: str, detalle: str, **valores: Any) -> dict[str, Any]:
    return {"clave": f"{codigo}:{modulo.id}:{fecha.isoformat()}:{detalle_clave}", "codigo": codigo,
            "severidad": severidad, "destino": destino, "icono": icono, "titulo": titulo, "detalle": detalle,
            "fecha": fecha, "valores": valores}


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


# --- Consulta y confirmación ---------------------------------------------------------------


def avisos(db: Session, modulo: Modulo, *, ahora: dt.datetime | None = None) -> list[dict[str, Any]]:
    """Los avisos de este momento, cada uno con ``enviado`` (si ya se confirmó su envío)."""
    ahora = ahora or ahora_lima()
    hoy = ahora.date()
    ayer = hoy - dt.timedelta(days=1)
    lista = [*_avisos_ingesta(db, modulo, hoy, ahora), *_aviso_mds(db, modulo, ayer), *_aviso_riego(db, modulo, ayer)]
    enviados = repo.claves_avisadas(db, [a["clave"] for a in lista], accion=auditoria_service.AVISO_ENVIADO,
                                    entidad=auditoria_service.ENTIDAD_AVISO)
    for a in lista:
        a["enviado"] = a["clave"] in enviados
    lista.sort(key=lambda a: ORDEN_SEVERIDAD[a["severidad"]])
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
