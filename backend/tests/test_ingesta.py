"""Ingesta de APIs (§3.6) con las APIs falsas: lecturas, crudos y ambiente; idempotencia; el Excel
histórico no se pisa; aislamiento de errores por fuente; rango automático con el reloj a las 23:30
de Lima; corridas programadas sin duplicar entre procesos; reproceso de WeatherLink; y que ninguna
clave ni token aparezca en la BD ni en los logs."""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import logging
from contextlib import contextmanager

import httpx
import pandas as pd
import pytest
import time_machine
from sqlalchemy import func, select

from app.core.errores import Conflicto, DatosInvalidos
from app.db.session import unidad_de_trabajo
from app.integraciones.phytech.cliente import ClientePhytech
from app.integraciones.weatherlink import conversion
from app.integraciones.weatherlink.cliente import ClienteWeatherLink
from app.models import (
    AmbienteDiario,
    IngestaCorrida,
    IngestaCrudo,
    MeteoLectura,
    NdviImagen,
    PhytechPlantaDiario,
    PhytechSueloHorario,
    PronosticoClima,
)
from app.models.enums import DisparoIngesta, EstadoIngesta, OrigenMeteo
from app.repositories import datos_campo as repo_datos
from app.repositories import ingestas as repo_ingestas
from app.services import ingesta_service, lecturas_service
from app.services.ingesta_service import Clientes
from tests.apis_falsas import (
    PH_SECRET,
    PROJECT,
    SECRETOS,
    WL_KEY,
    WL_SECRET,
    ApisFalsas,
    dia_wl,
    registro_wl,
    sin_espera,
)

HOY = dt.date(2026, 11, 8)
D1, D2, D3 = dt.date(2026, 11, 5), dt.date(2026, 11, 6), dt.date(2026, 11, 7)
MANANA_LIMA = "2026-11-08 10:00 -05:00"


@pytest.fixture
def reloj():
    with time_machine.travel(MANANA_LIMA, tick=False) as viaje:
        yield viaje


@pytest.fixture
def fundo(db):
    return repo_datos.fundo_por_nombre(db, "ENSUEÑO 1")


def _sesion(db):
    @contextmanager
    def _abrir():
        with unidad_de_trabajo(db) as sesion:
            yield sesion

    return _abrir


def _correr(db, apis: ApisFalsas, fuentes=ingesta_service.FUENTES, desde=D1, hasta=D3, clientes=None):
    corridas = ingesta_service.crear_corridas(db, fuentes, disparo=DisparoIngesta.script, desde=desde, hasta=hasta)
    db.commit()
    clientes = clientes or Clientes(weatherlink=apis.weatherlink, phytech=apis.phytech)
    resultado = ingesta_service.ejecutar_en_sesiones([c.id for c in corridas], clientes, sesion=_sesion(db))
    clientes.cerrar()
    return {c.fuente: c for c in resultado}


def _contar(db, modelo, *condiciones) -> int:
    return db.scalar(select(func.count()).select_from(modelo).where(*condiciones))


def _texto_bd(db) -> str:
    corridas = [json.dumps({"errores": c.errores, "fuente": c.fuente}, default=str)
                for c in db.scalars(select(IngestaCorrida))]
    crudos = [json.dumps({"e": c.endpoint, "p": c.parametros, "d": c.payload}, default=str)
              for c in db.scalars(select(IngestaCrudo))]
    return "\n".join(corridas + crudos)


# --- Ingesta completa -----------------------------------------------------------

def test_ingesta_guarda_lecturas_convertidas_crudos_y_ambiente(db, fundo, reloj, caplog):
    caplog.set_level(logging.DEBUG)
    apis = ApisFalsas(ndvi_fechas=[D2])
    corridas = _correr(db, apis)

    assert {f: c.estado for f, c in corridas.items()} == {f: EstadoIngesta.ok for f in ingesta_service.FUENTES}
    assert corridas["weatherlink"].filas_nuevas == 144
    assert corridas["pronostico"].desde == HOY == corridas["pronostico"].hasta

    # WeatherLink: °F → °C (77,5 °F = 25,3 °C), pulgadas → mm, millas → km; el de las 24:00 queda
    # como «D 00:00» (corte de día del Excel).
    lecturas = list(db.scalars(select(MeteoLectura).order_by(MeteoLectura.fecha_hora)))
    assert len(lecturas) == 144 and {l.origen for l in lecturas} == {OrigenMeteo.weatherlink}
    primera = lecturas[0]
    assert primera.fecha_hora == dt.datetime(2026, 11, 5, 0, 0)
    assert (primera.temp, primera.temp_max, primera.temp_min) == (25.3, 25.3, 24.7)
    assert primera.eto == 0.1 and primera.viento == 0.8 and primera.hr == 70

    # Phytech: solo el project del plot; pronóstico con fecha de captura.
    assert _contar(db, PhytechSueloHorario, PhytechSueloHorario.project_id == PROJECT) == 72
    assert _contar(db, PhytechSueloHorario, PhytechSueloHorario.project_id != PROJECT) == 0
    planta = db.scalars(select(PhytechPlantaDiario).order_by(PhytechPlantaDiario.fecha)).all()
    assert [p.fecha for p in planta] == [D1, D2, D3] and planta[0].et_mm == 4.3
    assert db.scalar(select(NdviImagen.fecha)) == D2
    assert {p.capturado_fecha for p in db.scalars(select(PronosticoClima))} == {HOY}

    # ambiente_diario recalculado para los días tocados (solo días cerrados).
    ambiente = {a.fecha: a for a in db.scalars(select(AmbienteDiario))}
    assert set(ambiente) == {D1, D2, D3}
    assert all(a.tiene_meteo == 1 and a.tiene_suelo == 1 and a.tiene_planta == 1 for a in ambiente.values())
    assert ambiente[D1].eto_mm == pytest.approx(4.8)  # 48 × 0,004 pulgadas × 25,4

    # Un crudo por llamada: 3 días de WeatherLink + 1 tramo por fuente de Phytech.
    crudos = db.scalars(select(IngestaCrudo).order_by(IngestaCrudo.id)).all()
    assert [c.endpoint for c in crudos].count("historic/28494") == 3 and len(crudos) == 7
    assert crudos[0].parametros["dia"] == "2026-11-05"

    tokens = [f"token-falso-{i:04d}" for i in range(1, apis.token_n + 1)]
    texto = _texto_bd(db) + caplog.text
    for secreto in (*SECRETOS, *tokens):
        assert secreto not in texto


def test_ingesta_repetida_no_duplica_ni_cambia(db, reloj):
    apis = ApisFalsas(ndvi_fechas=[D2])
    _correr(db, apis)
    segunda = _correr(db, apis)
    for fuente in ("weatherlink", "phytech_suelo", "phytech_planta", "ndvi", "pronostico"):
        assert segunda[fuente].filas_nuevas == 0 and segunda[fuente].filas_actualizadas == 0, fuente
    assert segunda["weatherlink"].filas_omitidas == 144
    assert _contar(db, MeteoLectura) == 144 and _contar(db, AmbienteDiario) == 3


def test_weatherlink_no_pisa_el_excel_historico(db, fundo, reloj):
    excel = conversion.lecturas_saneadas(
        [dict(r, temp_out_hi=50.0, temp_out_lo=49.0, temp_out=49.5) for r in dia_wl(D1)], "ENSUEÑO 1"
    )[0]
    lecturas_service.guardar_meteo(db, fundo, excel, origen=OrigenMeteo.excel_historico, corrida_id=None)
    corrida = _correr(db, ApisFalsas(), fuentes=["weatherlink"])["weatherlink"]
    assert corrida.filas_omitidas == 48 and corrida.filas_nuevas == 96
    del_excel = db.scalars(select(MeteoLectura).where(MeteoLectura.origen == OrigenMeteo.excel_historico)).all()
    assert len(del_excel) == 48 and {l.temp for l in del_excel} == {10.0}


def test_suelo_no_reemplaza_una_hora_con_dato_por_un_hueco(db, reloj):
    _correr(db, ApisFalsas(), fuentes=["phytech_suelo"], desde=D1, hasta=D1)
    hueco = ApisFalsas(humedad=lambda _d, h: None if 10 <= h < 12 else 30.0 + h / 10)
    corrida = _correr(db, hueco, fuentes=["phytech_suelo"], desde=D1, hasta=D1)["phytech_suelo"]
    assert corrida.estado == EstadoIngesta.ok and corrida.filas_actualizadas == 0
    assert _contar(db, PhytechSueloHorario, PhytechSueloHorario.hay_dato.is_(True)) == 24


# --- Errores --------------------------------------------------------------------

def test_error_de_credenciales_en_phytech_no_detiene_weatherlink(db, reloj, caplog):
    caplog.set_level(logging.DEBUG)
    apis = ApisFalsas()

    def phytech_mal() -> ClientePhytech:
        return ClientePhytech(api_key="clave-que-no-sirve-55", api_secret=PH_SECRET, base_url="https://api.phytech.test",
                              transport=apis.transporte(), reintentos=sin_espera())

    clientes = Clientes(weatherlink=apis.weatherlink, phytech=phytech_mal)
    corridas = _correr(db, apis, clientes=clientes)
    assert corridas["weatherlink"].estado == EstadoIngesta.ok
    for fuente in ("phytech_suelo", "phytech_planta", "ndvi", "pronostico"):
        assert corridas[fuente].estado == EstadoIngesta.error
        assert corridas[fuente].errores[0]["tipo"] == "credenciales"
        assert corridas[fuente].errores[0]["endpoint"] == "/auth/api-token"
    texto = _texto_bd(db) + caplog.text
    assert "clave-que-no-sirve-55" not in texto and PH_SECRET not in texto


def test_un_dia_que_falla_deja_la_corrida_parcial(db, reloj):
    # El segundo día responde 500 en los 4 intentos; los otros dos se guardan.
    apis = ApisFalsas()
    llamadas = {"n": 0}

    def con_falla(peticion: httpx.Request) -> httpx.Response:
        llamadas["n"] += 1
        if 2 <= llamadas["n"] <= 5:
            return httpx.Response(500)
        return apis(peticion)

    def weatherlink() -> ClienteWeatherLink:
        return ClienteWeatherLink(api_key=WL_KEY, api_secret=WL_SECRET, base_url="https://api.weatherlink.test/v2",
                                  station_id=28494, transport=httpx.MockTransport(con_falla), reintentos=sin_espera())

    corrida = _correr(db, apis, fuentes=["weatherlink"], clientes=Clientes(weatherlink=weatherlink))["weatherlink"]
    assert corrida.estado == EstadoIngesta.parcial and corrida.filas_nuevas == 96
    assert corrida.errores == [{"tipo": "reintentos_agotados", "status_code": 500, "endpoint": "/v2/historic/28494",
                                "mensaje": "Sin respuesta válida tras 4 intentos (HTTP 500)"}]
    assert _contar(db, AmbienteDiario) == 2


def test_error_inesperado_en_una_fuente_queda_registrado_y_sigue_con_las_demas(db, reloj, monkeypatch):
    def rompe(*_args, **_kwargs):
        raise RuntimeError(f"fallo raro con {SECRETOS[2]}")

    monkeypatch.setattr(ingesta_service.phytech_adaptador, "planta_diario", rompe)
    corridas = _correr(db, ApisFalsas(), fuentes=["phytech_planta", "weatherlink"])
    planta = corridas["phytech_planta"]
    assert planta.estado == EstadoIngesta.error and planta.errores[0]["tipo"] == "interno"
    assert corridas["weatherlink"].estado == EstadoIngesta.ok
    assert _contar(db, PhytechPlantaDiario) == 0 and _contar(db, MeteoLectura) == 144
    assert _contar(db, IngestaCrudo, IngestaCrudo.corrida_id == planta.id) == 0  # deshecho con el SAVEPOINT


def test_sin_claves_configuradas_es_error_de_configuracion(db, reloj):
    corridas = _correr(db, ApisFalsas(), fuentes=["weatherlink", "pronostico"], clientes=Clientes())
    assert {c.errores[0]["tipo"] for c in corridas.values()} == {"configuracion"}


# --- Rango automático y zona horaria --------------------------------------------

def _meteo_dias(db, fundo, dias):
    filas = []
    for dia in dias:
        for k in range(48):
            filas.append({"fundo_id": fundo.id, "fecha_hora": dt.datetime.combine(dia, dt.time()) + dt.timedelta(minutes=30 * k),
                          "origen": OrigenMeteo.weatherlink, "corrida_id": None,
                          **{c: 20.0 for c in repo_datos.COLUMNAS_METEO}})
    repo_datos.upsert_meteo(db, filas)


def _dias(desde, hasta):
    return [desde + dt.timedelta(days=i) for i in range((hasta - desde).days + 1)]


def test_rango_automatico_con_el_reloj_a_las_23_30_de_lima(db, fundo):
    # 23:30 en Lima ya es el día siguiente en UTC: "hoy" debe seguir siendo el 8 y "ayer" el 7.
    with time_machine.travel("2026-11-08 23:30 -05:00", tick=False):
        from app.core.tiempo import hoy_lima

        hoy = hoy_lima()
        assert hoy == HOY
        rango = ingesta_service.rango_automatico
        assert rango(db, "weatherlink", fundo, hoy) == (dt.date(2026, 11, 1), D3)  # sin datos: 7 días
        assert rango(db, "pronostico", fundo, hoy) == (HOY, HOY)
        assert rango(db, "ndvi", fundo, hoy) == (dt.date(2026, 10, 29), D3)
        _meteo_dias(db, fundo, _dias(dt.date(2026, 10, 20), D1))
        assert rango(db, "weatherlink", fundo, hoy) == (dt.date(2026, 11, 2), D3)  # última − 3 días
        db.execute(MeteoLectura.__table__.delete().where(
            func.date(MeteoLectura.fecha_hora) == dt.date(2026, 10, 30)))
        assert rango(db, "weatherlink", fundo, hoy) == (dt.date(2026, 10, 30), D3)  # empieza en el hueco


def test_rango_automatico_tiene_tope(db, fundo):
    _meteo_dias(db, fundo, [dt.date(2025, 1, 1)])
    desde, hasta = ingesta_service.rango_automatico(db, "weatherlink", fundo, HOY)
    assert (hasta - desde).days + 1 == ingesta_service.MAX_DIAS_AUTOMATICO and hasta == D3


def test_validar_rango():
    validar = ingesta_service.validar_rango
    assert validar(None, None, HOY) == (None, None)
    assert validar(None, D2, HOY) == (D2, D2)
    assert validar(D1, None, HOY) == (D1, D3)
    for desde, hasta in ((D3, D1), (D1, HOY)):
        with pytest.raises(ValueError):
            validar(desde, hasta, HOY)
    with pytest.raises(ValueError):
        validar(dt.date(2026, 1, 1), D3, HOY, maximo=62)


# --- Manual, programada y colgadas ----------------------------------------------

def test_lanzar_manual_valida_y_evita_dos_corridas_en_curso(db, crear_usuario, reloj):
    usuario = crear_usuario("ana", rol="encargado")
    corridas = ingesta_service.lanzar_manual(db, ["weatherlink", "ndvi"], usuario_id=usuario.id)
    assert [(c.fuente, c.disparo, c.estado, c.desde) for c in corridas] == [
        ("weatherlink", DisparoIngesta.manual, EstadoIngesta.en_curso, None),
        ("ndvi", DisparoIngesta.manual, EstadoIngesta.en_curso, None),
    ]
    with pytest.raises(Conflicto):
        ingesta_service.lanzar_manual(db, ["ndvi"], usuario_id=usuario.id)
    with pytest.raises(DatosInvalidos):
        ingesta_service.lanzar_manual(db, ["clima_marciano"], usuario_id=usuario.id)
    with pytest.raises(DatosInvalidos):
        ingesta_service.lanzar_manual(db, ["phytech_suelo"], usuario_id=usuario.id, desde=D1, hasta=HOY)


def test_corridas_sin_latido_se_cierran_como_interrumpidas(db, reloj):
    viva, muerta = ingesta_service.crear_corridas(db, ["weatherlink", "ndvi"], disparo=DisparoIngesta.manual)
    hace_9_h = dt.datetime(2026, 11, 8, 6, tzinfo=dt.UTC)  # 01:00 Lima
    viva.inicio_at = muerta.inicio_at = hace_9_h
    viva.latido_at = dt.datetime(2026, 11, 8, 14, 58, tzinfo=dt.UTC)   # hace 2 min: sigue corriendo
    muerta.latido_at = dt.datetime(2026, 11, 8, 14, 49, tzinfo=dt.UTC)  # hace 11 min: sin dueño
    db.flush()
    assert ingesta_service.cerrar_colgadas(db) == [(muerta.id, "ndvi", None)]
    db.refresh(muerta)
    db.refresh(viva)
    assert muerta.estado == EstadoIngesta.error and muerta.errores[0]["tipo"] == "interrumpida"
    assert viva.estado == EstadoIngesta.en_curso
    # Sin latido nunca registrado se cuenta desde el inicio.
    viva.latido_at = None
    db.flush()
    assert [c[0] for c in ingesta_service.cerrar_colgadas(db)] == [viva.id]


def test_dos_actualizar_ahora_a_la_vez_dan_409_por_el_indice_unico(db, crear_usuario, reloj, monkeypatch):
    """La consulta previa no ve la corrida que otra sesión aún no confirmó: lo frena el índice único
    parcial ``uq_ingesta_corrida_en_curso`` y se responde Conflicto (la sesión sigue usable)."""
    usuario = crear_usuario("ana", rol="encargado")
    primera = ingesta_service.lanzar_manual(db, ["weatherlink"], usuario_id=usuario.id)
    monkeypatch.setattr(repo_ingestas, "en_curso", lambda _db, _fuentes: [])  # carrera simulada
    with pytest.raises(Conflicto):
        ingesta_service.lanzar_manual(db, ["weatherlink", "ndvi"], usuario_id=usuario.id)
    # La programada se omite si la fuente está ocupada (también en carrera).
    assert repo_ingestas.reclamar_programada(db, "weatherlink", HOY, primera[0].inicio_at) is None
    monkeypatch.undo()
    en_curso = db.scalars(select(IngestaCorrida).where(IngestaCorrida.estado == EstadoIngesta.en_curso)).all()
    assert [c.id for c in en_curso] == [primera[0].id]  # tampoco quedó la de ndvi
    assert repo_ingestas.reclamar_programada(db, "weatherlink", HOY, primera[0].inicio_at) is None
    assert repo_ingestas.reclamar_programada(db, "ndvi", HOY, primera[0].inicio_at) is not None


def test_latido_actualiza_la_corrida_mientras_corre(db):
    import time

    corrida = ingesta_service.crear_corridas(db, ["weatherlink"], disparo=DisparoIngesta.script)[0]
    corrida.latido_at = None
    db.commit()
    with ingesta_service.Latido(corrida.id, cada=0.05, sesion=_sesion(db)) as latido:
        time.sleep(0.4)
    latido._hilo.join(2)
    db.refresh(corrida)
    assert latido.latidos >= 1 and corrida.latido_at is not None


def test_vigilante_repite_la_programada_interrumpida_de_hoy(db, reloj, monkeypatch):
    """El proceso murió a mitad de la ingesta programada y volvió enseguida: en cuanto vence el
    latido, el vigilante cierra la corrida y la vuelve a ejecutar; un error de la API no se repite."""
    from app.jobs import tareas

    ejecutadas: list[list[int]] = []
    monkeypatch.setattr(tareas, "unidad_de_trabajo", _sesion(db))
    monkeypatch.setattr(ingesta_service, "ejecutar_en_sesiones", lambda ids: ejecutadas.append(list(ids)) or [])
    ids = tareas.ingesta_diaria()
    corridas = {c.fuente: c for c in db.scalars(select(IngestaCorrida).where(IngestaCorrida.id.in_(ids)))}
    for corrida in corridas.values():
        corrida.estado = EstadoIngesta.ok
    corridas["phytech_suelo"].estado = EstadoIngesta.error
    corridas["phytech_suelo"].errores = [{"tipo": "red"}]
    corridas["weatherlink"].estado = EstadoIngesta.en_curso
    corridas["weatherlink"].latido_at = dt.datetime(2026, 11, 8, 14, 45, tzinfo=dt.UTC)  # hace 15 min
    db.flush()

    assert tareas.vigilar_ingestas(ya_es_hora=False) == []  # antes de la hora solo cierra
    db.refresh(corridas["weatherlink"])
    assert corridas["weatherlink"].errores[0]["tipo"] == "interrumpida"
    assert tareas.vigilar_ingestas() == [corridas["weatherlink"].id]
    assert ejecutadas[-1] == [corridas["weatherlink"].id]
    db.refresh(corridas["weatherlink"])
    assert corridas["weatherlink"].estado == EstadoIngesta.en_curso
    assert tareas.vigilar_ingestas() == []  # en curso con latido fresco; suelo (error de red) no


def test_si_no_se_puede_guardar_la_corrida_queda_en_error_y_no_en_curso(db, reloj):
    corrida = ingesta_service.crear_corridas(db, ["pronostico"], disparo=DisparoIngesta.script)[0]
    db.commit()
    usos = {"n": 0}

    @contextmanager
    def sesion_que_falla_al_confirmar():
        usos["n"] += 1
        with unidad_de_trabajo(db) as sesion:
            yield sesion
            if usos["n"] == 2:  # la transacción de la ingesta
                raise RuntimeError("se cayó la conexión")

    apis = ApisFalsas()
    clientes = Clientes(weatherlink=apis.weatherlink, phytech=apis.phytech)
    assert ingesta_service.ejecutar_en_sesiones([corrida.id], clientes, sesion=sesion_que_falla_al_confirmar) == []
    clientes.cerrar()
    db.refresh(corrida)
    assert corrida.estado == EstadoIngesta.error and corrida.errores[0]["tipo"] == "interno"
    assert "No se pudo guardar" in corrida.errores[0]["mensaje"]


def test_corrida_programada_una_sola_vez_por_fuente_y_dia(db, reloj):
    ahora = dt.datetime(2026, 11, 8, 10, tzinfo=dt.UTC)
    primera = repo_ingestas.reclamar_programada(db, "weatherlink", HOY, ahora)
    assert primera is not None
    assert repo_ingestas.reclamar_programada(db, "weatherlink", HOY, ahora) is None  # otro proceso
    corrida = db.get(IngestaCorrida, primera)
    for estado, se_repite in ((EstadoIngesta.ok, False), (EstadoIngesta.parcial, False), (EstadoIngesta.error, True)):
        corrida.estado, corrida.errores = estado, [{"tipo": "red"}]
        db.flush()
        reclamada = repo_ingestas.reclamar_programada(db, "weatherlink", HOY, ahora)
        assert (reclamada == primera) is se_repite, estado
    db.refresh(corrida)
    assert corrida.estado == EstadoIngesta.en_curso and corrida.errores == []


def test_tarea_diaria_reclama_y_ejecuta_sin_duplicar(db, reloj, monkeypatch):
    from app.jobs import tareas

    ejecutadas: list[list[int]] = []
    monkeypatch.setattr(tareas, "unidad_de_trabajo", _sesion(db))
    monkeypatch.setattr(ingesta_service, "ejecutar_en_sesiones", lambda ids: ejecutadas.append(list(ids)) or [])
    ids = tareas.ingesta_diaria()
    assert len(ids) == len(ingesta_service.FUENTES) and ejecutadas == [ids]
    programadas = db.scalars(select(IngestaCorrida).where(IngestaCorrida.fecha_programada == HOY)).all()
    assert {c.disparo for c in programadas} == {DisparoIngesta.programado}
    assert tareas.ingesta_diaria() == [] and len(ejecutadas) == 1  # segundo proceso (o reinicio)


def test_programador_vigila_las_ingestas_cada_5_minutos():
    from apscheduler.schedulers.background import BackgroundScheduler

    from app.core.tiempo import zona_lima
    from app.jobs.runner import configurar

    trabajos = {t.id: t for t in configurar(BackgroundScheduler(timezone=zona_lima())).get_jobs()}
    assert trabajos["vigilar_ingestas"].trigger.interval == dt.timedelta(minutes=5)


def test_programador_lanza_la_ingesta_a_la_hora_y_al_arrancar_tarde():
    from apscheduler.schedulers.background import BackgroundScheduler

    from app.core.tiempo import zona_lima
    from app.jobs.runner import configurar, ingesta_al_arrancar

    temprano = dt.datetime(2026, 11, 8, 4, 59, tzinfo=zona_lima())
    tarde = dt.datetime(2026, 11, 8, 5, 0, tzinfo=zona_lima())
    assert ingesta_al_arrancar(temprano) is None
    assert ingesta_al_arrancar(tarde) == tarde + dt.timedelta(seconds=30)
    programador = configurar(BackgroundScheduler(timezone=zona_lima()), ahora=temprano)
    trabajos = {t.id: t for t in programador.get_jobs()}
    assert "ingesta_al_arrancar" not in trabajos
    campos = {f.name: str(f) for f in trabajos["ingesta_diaria"].trigger.fields}
    assert campos["hour"] == "5" and campos["minute"] == "0"
    assert "ingesta_al_arrancar" in {t.id for t in configurar(BackgroundScheduler(timezone=zona_lima()), ahora=tarde).get_jobs()}


# --- Reproceso de WeatherLink ---------------------------------------------------

def test_reprocesar_weatherlink_aplica_reglas_nuevas_sin_descargar(db, fundo, reloj, monkeypatch):
    excel = conversion.lecturas_saneadas(
        [dict(r, temp_out_hi=50.0, temp_out_lo=49.0, temp_out=49.5) for r in dia_wl(D3)], "ENSUEÑO 1"
    )[0]
    lecturas_service.guardar_meteo(db, fundo, excel, origen=OrigenMeteo.excel_historico, corrida_id=None)
    apis = ApisFalsas()
    _correr(db, apis, fuentes=["weatherlink"])
    peticiones = len(apis.peticiones)
    t_antes = db.scalar(select(AmbienteDiario.t_media).where(AmbienteDiario.fecha == D1))

    # La empresa decide que T° Prom sea la temperatura del intervalo (temp_out = 77 °F = 25,0 °C).
    reglas = tuple(dataclasses.replace(r, campo="temp_out") if r.columna == "T" else r for r in conversion.REGLAS)
    monkeypatch.setattr(conversion, "REGLAS", reglas)
    resultado = ingesta_service.reprocesar_weatherlink(db, D1 - dt.timedelta(days=1), D3)

    assert len(apis.peticiones) == peticiones  # sin llamadas a la API
    assert resultado.dias_con_crudo == 3 and resultado.dias_sin_crudo == [D1 - dt.timedelta(days=1)]
    assert resultado.conteo.actualizadas == 96 and resultado.conteo.omitidas == 48  # D3 es del Excel
    temps = set(db.scalars(select(MeteoLectura.temp).where(MeteoLectura.origen == OrigenMeteo.weatherlink)))
    assert temps == {25.0}
    assert set(db.scalars(select(MeteoLectura.temp).where(MeteoLectura.origen == OrigenMeteo.excel_historico))) == {10.0}
    t_despues = db.scalar(select(AmbienteDiario.t_media).where(AmbienteDiario.fecha == D1))
    assert t_antes == pytest.approx(25.3) and t_despues == pytest.approx(25.0)
    corrida = db.get(IngestaCorrida, resultado.corrida_id)
    assert corrida.fuente == "reprocesar_weatherlink" and corrida.estado == EstadoIngesta.ok


def test_reprocesar_usa_el_ultimo_payload_de_cada_dia(db, reloj):
    _correr(db, ApisFalsas(), fuentes=["weatherlink"], desde=D1, hasta=D1)
    _correr(db, ApisFalsas(wl_registros=lambda d: dia_wl(d, temp_f=86.0)), fuentes=["weatherlink"], desde=D1, hasta=D1)
    crudos = repo_ingestas.crudos_weatherlink(db, D1, D1)
    assert len(crudos) == 1 and crudos[0].payload["sensors"][1]["data"][0]["temp_out"] == 86.0
    assert pd.Series(list(db.scalars(select(MeteoLectura.temp)))).eq(30.3).all()  # 86,5 °F


def test_weatherlink_descarta_registros_de_otro_dia(db, reloj):
    """Si la API devolviera también el registro de las 00:00 del día pedido (cierra el anterior),
    no se mezcla con el día pedido."""
    def con_extra(dia):
        inicio = int(dt.datetime.combine(dia, dt.time(), tzinfo=dt.timezone(dt.timedelta(hours=-5))).timestamp())
        return [registro_wl(inicio, temp_f=99.0), *dia_wl(dia)]

    corrida = _correr(db, ApisFalsas(wl_registros=con_extra), fuentes=["weatherlink"], desde=D2, hasta=D2)["weatherlink"]
    assert corrida.filas_nuevas == 48
    fechas = set(db.scalars(select(MeteoLectura.fecha_hora)))
    assert {f.date() for f in fechas} == {D2} and 37.5 not in set(db.scalars(select(MeteoLectura.temp)))


def _dia_corte_anterior(dia):
    """Payload de un día pedido con el corte anterior: ``ts`` de 00:00 a 23:30, temperatura
    distinta en cada registro."""
    inicio = int(dt.datetime.combine(dia, dt.time(), tzinfo=dt.timezone(dt.timedelta(hours=-5))).timestamp())
    return [registro_wl(inicio + 1800 * k, temp_f=60.0 + dia.day + k * 0.25) for k in range(48)]


def test_reprocesar_corrige_lo_guardado_con_el_corte_anterior(db, fundo, reloj, monkeypatch):
    with monkeypatch.context() as parche:
        parche.setattr(conversion, "MEDIANOCHE_AL_DIA_QUE_TERMINA", False)
        _correr(db, ApisFalsas(wl_registros=_dia_corte_anterior), fuentes=["weatherlink"], desde=D1, hasta=D2)
    medianoche_d1 = dt.datetime.combine(D1, dt.time())
    antes = db.scalar(select(MeteoLectura.temp).where(MeteoLectura.fecha_hora == medianoche_d1))

    resultado = ingesta_service.reprocesar_weatherlink(db, D1, D2)

    lecturas = {l.fecha_hora: l for l in db.scalars(select(MeteoLectura))}
    por_dia = pd.Series([f.date() for f in lecturas]).value_counts().to_dict()
    # D1: 00:30..23:30 de su payload + el de las 24:00 (ts D2 00:00, del payload de D2) como D1 00:00.
    # D2: le falta el de las 24:00 (estaría en el payload de D3); su «00:00» viejo se borra.
    assert por_dia == {D1: 48, D2: 47} and resultado.borradas == 1
    ts_d2 = int(dt.datetime.combine(D2, dt.time(), tzinfo=dt.timezone(dt.timedelta(hours=-5))).timestamp())
    esperado = conversion.convertir([registro_wl(ts_d2, temp_f=60.0 + D2.day)], "X").iloc[0]
    assert lecturas[medianoche_d1].temp == esperado["T"] != antes
    assert dt.datetime.combine(D2, dt.time()) not in lecturas
    ambiente = {a.fecha: a for a in db.scalars(select(AmbienteDiario))}
    assert set(ambiente) == {D1, D2}
    # Repetirlo no cambia nada.
    otra = ingesta_service.reprocesar_weatherlink(db, D1, D2)
    assert otra.borradas == 0 and otra.conteo.nuevas == 0 and otra.conteo.actualizadas == 0


def test_reprocesar_pisar_excel_reemplaza_el_excel_del_rango_y_lo_audita(db, fundo, reloj):
    from app.models import Auditoria

    excel = conversion.lecturas_saneadas(
        [dict(r, temp_out_hi=50.0, temp_out_lo=49.0, temp_out=49.5) for r in dia_wl(D3)], "ENSUEÑO 1"
    )[0]
    lecturas_service.guardar_meteo(db, fundo, excel, origen=OrigenMeteo.excel_historico, corrida_id=None)
    _correr(db, ApisFalsas(), fuentes=["weatherlink"])
    assert _contar(db, MeteoLectura, MeteoLectura.origen == OrigenMeteo.excel_historico) == 48

    with pytest.raises(ValueError):
        ingesta_service.reprocesar_weatherlink(db, D3 - dt.timedelta(days=31), D3, pisar_excel=True)
    sin_pisar = ingesta_service.reprocesar_weatherlink(db, D3, D3)
    assert sin_pisar.conteo.omitidas == 48
    assert _contar(db, MeteoLectura, MeteoLectura.origen == OrigenMeteo.excel_historico) == 48

    resultado = ingesta_service.reprocesar_weatherlink(db, D3, D3, pisar_excel=True)
    assert resultado.conteo.actualizadas == 48
    assert _contar(db, MeteoLectura, MeteoLectura.origen == OrigenMeteo.excel_historico) == 0
    assert set(db.scalars(select(MeteoLectura.temp).where(MeteoLectura.fecha_hora >= dt.datetime(2026, 11, 7)))) == {25.3}
    assert db.scalar(select(AmbienteDiario.t_media).where(AmbienteDiario.fecha == D3)) == pytest.approx(25.3)
    auditoria = db.scalars(select(Auditoria).where(Auditoria.accion == "meteo_excel_pisado")).all()
    assert len(auditoria) == 1 and auditoria[0].entidad_id == str(resultado.corrida_id)
    assert auditoria[0].detalle["lecturas_reemplazadas"] == 48
    assert auditoria[0].detalle["por_dia"] == {"2026-11-07": 48}
