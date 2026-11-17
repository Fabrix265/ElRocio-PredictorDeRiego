"""Riego real del controlador Galileo (Fabric): llave de válvulas -> turno, m³ -> m³/ha, y versiones
aplicadas que reemplazan al provisional del cronograma sin borrarlo (ni pisar lo manual)."""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

import pytest
import time_machine
from sqlalchemy import select

from app.db.session import unidad_de_trabajo
from app.integraciones.galileo import adaptador
from app.integraciones.galileo.config import ConfiguracionFabric
from app.models import IngestaCrudo, RiegoRegistro, Turno
from app.models.enums import DisparoIngesta, EstadoIngesta, EstadoRiego, OrigenRiego
from app.services import ingesta_service
from app.services.ingesta_service import Clientes
from app.services.riego_service import _crear_registro
from tests.apis_falsas import ApisFalsas, ClienteGalileoFalso, fila_galileo

D1, D2 = dt.date(2026, 11, 5), dt.date(2026, 11, 6)


class _T:
    def __init__(self, id, codigo, area_ha, valvula_controlador):
        self.id, self.codigo, self.area_ha, self.valvula_controlador = id, codigo, area_ha, valvula_controlador


TURNOS = [_T(1, "TE01", 13.019, "6061000"), _T(4, "TE04", 12.459, "6667000")]
COLUMNAS = ClienteGalileoFalso(lambda d: []).columnas()


# --- Adaptador ------------------------------------------------------------------

@pytest.mark.parametrize(("valores", "esperada"), [
    ((66, 67, 0, 0, 0), "6667000"),
    ((66.0, "67", None, 0, 0.0), "6667000"),
    ((60, 61, 0, 0, 0), "6061000"),
])
def test_llave_concatena_valvulas(valores, esperada):
    assert adaptador.llave(valores) == esperada


@pytest.mark.parametrize(("valor", "minutos"), [
    ("05:01:00", 301), ("16:56", 1016), ("2026-11-05T05:01:00", 301), (dt.time(3, 15), 195),
    (dt.datetime(1899, 12, 30, 2, 54), 174), (dt.timedelta(hours=11, minutes=36), 696), (0.5, 720),
])
def test_hora_en_varios_formatos(valor, minutos):
    assert adaptador.minutos_de(valor) == pytest.approx(minutos)


def test_fecha_en_varios_formatos():
    assert adaptador.fecha_de(dt.datetime(2024, 10, 7)) == dt.date(2024, 10, 7)
    assert adaptador.fecha_de("2024-10-07 00:00:00") == dt.date(2024, 10, 7)
    assert adaptador.fecha_de("7/10/2024 00:00") == dt.date(2024, 10, 7)


def test_adaptar_agrupa_ciclos_y_calcula_m3_por_hectarea():
    filas = [
        fila_galileo(D1, "05:01:00", m3=200, minutos=45.06),
        fila_galileo(D1, "03:00:00", m3=150, minutos=30),
        fila_galileo(D1, "05:01:00", m3=200, minutos=45.06),  # duplicada exacta
        fila_galileo(D1, "07:00:00", valvulas=(60, 61, 0, 0, 0), m3=130.19, minutos=40),
        fila_galileo(D1, "08:00:00", valvulas=(10, 11, 0, 0, 0)),  # de otra consola
        fila_galileo(D1, "09:00:00", m3=0, minutos=0),  # sin agua
        fila_galileo(D1, "23:30:00", m3=50, minutos=60),  # termina al día siguiente
    ]
    r = adaptador.adaptar(filas, COLUMNAS, TURNOS)
    te04 = r.grupos[(4, D1)]
    assert [c["hora_inicio"] for c in te04] == ["03:00", "05:01", "23:30"]
    assert te04[1]["riego_m3"] == 200 and te04[1]["riego_m3ha"] == pytest.approx(200 / 12.459, abs=1e-4)
    assert te04[1]["duracion_min"] == 45.06 and te04[1]["hora_fin"] == "05:46"
    assert te04[2]["fin_dia_siguiente"] is True and te04[2]["hora_fin"] == "00:30"
    assert r.grupos[(1, D1)][0]["riego_m3ha"] == pytest.approx(10.0, abs=1e-3)
    assert r.duplicadas == 1 and r.vacias == 1 and dict(r.sin_turno) == {"1011000": 1}


def test_columnas_reales_y_formato_excel():
    reales = adaptador.resolver_columnas(["system", "time", "valve_a", "valve_b", "valve_c", "valve_d", "valve_e",
                                          "water_done", "time_water_done", "consola"])
    assert reales["fecha"] == reales["hora"] == "time" and reales["m3"] == "water_done"
    excel = adaptador.resolver_columnas(["fecha", "Hora", "Valve A", "Valve B", "Valve C", "Valve D", "Valve E",
                                         "Water Done", "Time Water Done", "Llave"])
    assert (excel["fecha"], excel["hora"], excel["minutos"]) == ("fecha", "Hora", "Time Water Done")
    fila = {"fecha": dt.datetime(2024, 10, 7), "Hora": "05:01:00", "Water Done": 200, "Time Water Done": 45.06,
            "Valve A": 66, "Valve B": 67, "Valve C": 0, "Valve D": 0, "Valve E": 0}
    r = adaptador.adaptar([fila], excel, TURNOS)
    assert r.grupos[(4, dt.date(2024, 10, 7))][0]["hora_inicio"] == "05:01"


def test_resolver_columnas_avisa_si_falta_alguna():
    with pytest.raises(ValueError, match="water done"):
        adaptador.resolver_columnas(["time", "valve_a", "valve_b", "valve_c", "valve_d", "valve_e"])


def test_tabla_calificada_rechaza_identificadores_raros():
    assert ConfiguracionFabric(esquema="dbo", tabla="silver_galileo_consolas").tabla_calificada() == \
        "[dbo].[silver_galileo_consolas]"
    with pytest.raises(ValueError):
        ConfiguracionFabric(esquema="dbo", tabla="x]; DROP TABLE y--").tabla_calificada()


# --- Ingesta --------------------------------------------------------------------

@pytest.fixture
def reloj():
    with time_machine.travel("2026-11-08 10:00 -05:00", tick=False):
        yield


def _sesion(db):
    @contextmanager
    def _abrir():
        with unidad_de_trabajo(db) as sesion:
            yield sesion

    return _abrir


def _correr(db, filas_por_dia, desde=D1, hasta=D2):
    corridas = ingesta_service.crear_corridas(db, [ingesta_service.GALILEO], disparo=DisparoIngesta.script,
                                              desde=desde, hasta=hasta)
    db.commit()
    apis = ApisFalsas(galileo_filas=filas_por_dia)
    clientes = Clientes(galileo=apis.galileo)
    resultado = ingesta_service.ejecutar_en_sesiones([c.id for c in corridas], clientes, sesion=_sesion(db))
    clientes.cerrar()
    return resultado[0]


def _te04(db) -> Turno:
    return db.scalar(select(Turno).where(Turno.valvula_controlador == "6667000"))


def _versiones(db, turno_id, fecha):
    return db.scalars(select(RiegoRegistro).where(RiegoRegistro.turno_id == turno_id, RiegoRegistro.fecha == fecha)
                      .order_by(RiegoRegistro.version)).all()


def _provisional(db, turno, fecha, m3ha=20.0):
    ciclo = {"inicio_min": 300.0, "fin_min": 360.0, "duracion_min": 60.0, "riego_m3ha": m3ha,
             "riego_m3": round(m3ha * turno.area_ha, 1), "area_ha": turno.area_ha,
             "valvula": turno.valvula_controlador, "hora_inicio": "05:00", "hora_fin": "06:00",
             "fin_dia_siguiente": False}
    _crear_registro(db, turno=turno, fecha=fecha, vigente=None, ciclos=[ciclo], estado=EstadoRiego.provisional,
                    origen=OrigenRiego.cronograma, actor=None)
    db.commit()


def test_el_riego_real_reemplaza_al_provisional_y_lo_conserva(db, reloj):
    turno = _te04(db)
    _provisional(db, turno, D1)
    corrida = _correr(db, lambda d: [fila_galileo(d, "05:01:00"), fila_galileo(d, "14:00:00", m3=100, minutos=22)])
    assert corrida.estado == EstadoIngesta.ok
    assert corrida.filas_actualizadas == 1 and corrida.filas_nuevas == 1  # D1 reemplaza, D2 nuevo

    plan, real = _versiones(db, turno.id, D1)
    assert (plan.estado, plan.origen, plan.vigente) == (EstadoRiego.provisional, OrigenRiego.cronograma, False)
    assert (real.estado, real.origen, real.vigente) == (EstadoRiego.aplicado, OrigenRiego.controlador, True)
    assert real.basado_en_id == plan.id and real.creado_por is None
    assert [c.hora_inicio for c in real.ciclos] == ["05:01", "14:00"]
    assert sum(c.riego_m3 for c in real.ciclos) == pytest.approx(300)

    crudos = db.scalars(select(IngestaCrudo).where(IngestaCrudo.corrida_id == corrida.id)).all()
    assert {c.parametros["dia"] for c in crudos} == {D1.isoformat(), D2.isoformat()}
    assert crudos[0].payload[0]["valve_a"] == 66 and crudos[0].payload[0]["consola"] == "GALENSUENO1"

    # Repetir la ingesta con los mismos datos no crea versiones.
    otra = _correr(db, lambda d: [fila_galileo(d, "05:01:00"), fila_galileo(d, "14:00:00", m3=100, minutos=22)])
    assert (otra.filas_nuevas, otra.filas_actualizadas, otra.filas_omitidas) == (0, 0, 2)
    assert len(_versiones(db, turno.id, D1)) == 2


def test_igual_al_historico_no_crea_version(db, reloj):
    # El histórico (Excel del mismo controlador) guarda la duración con 2 decimales y m³/ha sin
    # redondear: si el controlador trae lo mismo, no hay versión nueva.
    turno = _te04(db)
    ciclo = {"inicio_min": 301.0, "fin_min": 346.06, "duracion_min": 45.06, "riego_m3": 200.0,
             "riego_m3ha": 200 / turno.area_ha, "area_ha": turno.area_ha, "valvula": "6667000",
             "hora_inicio": "05:01", "hora_fin": "05:46", "fin_dia_siguiente": False}
    _crear_registro(db, turno=turno, fecha=D1, vigente=None, ciclos=[ciclo], estado=EstadoRiego.aplicado,
                    origen=OrigenRiego.historico, actor=None)
    db.commit()
    corrida = _correr(db, lambda d: [fila_galileo(d)], desde=D1, hasta=D1)
    assert (corrida.filas_nuevas, corrida.filas_actualizadas, corrida.filas_omitidas) == (0, 0, 1)
    assert [v.origen for v in _versiones(db, turno.id, D1)] == [OrigenRiego.historico]


def test_no_pisa_lo_registrado_a_mano(db, reloj):
    turno = _te04(db)
    ciclo = {"inicio_min": 300.0, "fin_min": 330.0, "duracion_min": 30.0, "riego_m3ha": 10.0, "riego_m3": 124.6,
             "area_ha": turno.area_ha, "valvula": "6667000", "hora_inicio": "05:00", "hora_fin": "05:30",
             "fin_dia_siguiente": False}
    _crear_registro(db, turno=turno, fecha=D1, vigente=None, ciclos=[ciclo], estado=EstadoRiego.aplicado,
                    origen=OrigenRiego.manual, actor=None, motivo="corrección")
    db.commit()
    corrida = _correr(db, lambda d: [fila_galileo(d)], desde=D1, hasta=D1)
    assert corrida.filas_omitidas == 1 and corrida.filas_nuevas == 0
    assert [v.origen for v in _versiones(db, turno.id, D1)] == [OrigenRiego.manual]


def test_sin_configuracion_la_fuente_queda_en_error_sin_red(db, reloj):
    corridas = ingesta_service.crear_corridas(db, [ingesta_service.GALILEO], disparo=DisparoIngesta.script,
                                              desde=D1, hasta=D1)
    db.commit()
    corrida = ingesta_service.ejecutar_en_sesiones([corridas[0].id], Clientes(), sesion=_sesion(db))[0]
    assert corrida.estado == EstadoIngesta.error
    assert corrida.errores[0]["tipo"] == "configuracion"
