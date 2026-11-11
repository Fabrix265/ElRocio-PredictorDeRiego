"""Datos de campo en la BD: guardar lecturas (idempotente), ambiente_diario desde la BD, riego
histórico por turno-día y Historial desde la BD (§2.3)."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
import time_machine
from riego_ml.dataset.limpieza import limpiar_ciclos, tabla_turno_dia
from riego_ml.dataset.unir import columnas_ambiente, construir_ambiente_diario
from riego_ml.sources.meteo import VARIABLES, meteo_diaria, sanear_meteo
from riego_ml.sources.ndvi import ndvi_diario
from riego_ml.sources.phytech import resumir_phytech
from riego_ml.sources.phytech_crudo import HUM_COLS
from riego_ml.sources.riego import COLUMNAS_RIEGO
from sqlalchemy import func, select

from app.ml.columnas import AMBIENTE_BD_A_ML, AMBIENTE_ML_A_BD, METEO_BD_A_ML
from app.ml.historial_bd import construir_historial
from app.models import (
    AmbienteDiario,
    Cronograma,
    CronogramaCiclo,
    CronogramaVersion,
    MeteoLectura,
    RiegoCiclo,
    RiegoRegistro,
)
from app.models.datos import COLUMNAS_AMBIENTE
from app.models.enums import OrigenMeteo, OrigenVersion
from app.repositories import datos_campo as repo
from app.services import ambiente_service, carga_historica, lecturas_service
from app.services.carga_historica import ResultadoFuente
from app.services.riego_contenido import hash_contenido

PROJECT = 907557
PLOT = 70208
FUNDO = "ENSUEÑO 1"
DIA = dt.date(2025, 1, 2)


@pytest.fixture
def fundo(db):
    return repo.fundo_por_nombre(db, FUNDO)


@pytest.fixture
def modulo(db):
    return repo.modulo_por_codigo(db, "EN01-MOD5")


def _lecturas(dia=DIA, n=48, t=20.0):
    horas = pd.date_range(pd.Timestamp(dia) + pd.Timedelta(minutes=30), periods=n, freq="30min")
    df = pd.DataFrame({"Fundo": FUNDO, "fecha_hora": horas})
    for variable in VARIABLES:
        df[variable] = 1.0
    df["T"] = t + np.arange(n) * 0.1
    df["T_max"], df["T_min"], df["HR"], df["HR_max"], df["ETo"] = t + 1, t - 1, 80.0, 85.0, 0.1
    return sanear_meteo(df)[0]


def _horario(dia=DIA, horas=24):
    fechas = pd.date_range(pd.Timestamp(dia), periods=horas, freq="h")
    df = pd.DataFrame({"fundo": FUNDO, "plot_id": PLOT, "project_id": PROJECT, "fecha_hora": fechas,
                       "hay_dato_phytech": 1})
    for c in [*HUM_COLS, "hum_zona_radicular", "hum_linea_estres"]:
        df[c] = 30.0 + np.arange(horas) * 0.5
    return df


def _planta(dia=DIA):
    return pd.DataFrame({"fundo": [FUNDO], "plot_id": [PLOT], "project_id": [PROJECT],
                         "fecha": [pd.Timestamp(dia)], "mds_contraccion_um": [120.0],
                         "crecimiento_tronco_um": [5.0], "estres_planta_ps": [0.3],
                         "tamano_fruto_mm": [np.nan], "crecimiento_fruto_mm": [np.nan]})


def _imagenes(dia, image_id="img-1"):
    fila = {"image_id": image_id, "date": pd.Timestamp(dia), "entity_type": "plot",
            "entity_id": PLOT, "no_vegetation": False}
    for k in range(5):
        fila.update({f"class{k}_color": "verde", f"class{k}_ndvi_min": 0.1 * k,
                     f"class{k}_ndvi_max": 0.1 * k + 0.1, f"class{k}_percent": 20.0})
    return pd.DataFrame([fila])


def test_mapeo_de_columnas_coincide_con_riego_ml():
    assert list(AMBIENTE_BD_A_ML.values()) == columnas_ambiente()
    assert list(AMBIENTE_BD_A_ML) == list(COLUMNAS_AMBIENTE)
    assert {v: k for k, v in AMBIENTE_ML_A_BD.items()} == AMBIENTE_BD_A_ML
    assert sorted(METEO_BD_A_ML.values()) == sorted(VARIABLES)
    assert set(METEO_BD_A_ML) == set(repo.COLUMNAS_METEO)


def test_guardar_meteo_es_idempotente_y_la_api_no_pisa_el_excel(db, fundo):
    lecturas = _lecturas()
    conteo, fechas = lecturas_service.guardar_meteo(db, fundo, lecturas, origen=OrigenMeteo.excel_historico,
                                                    corrida_id=None)
    assert (conteo.nuevas, conteo.actualizadas, conteo.omitidas) == (48, 0, 0)
    assert fechas == {DIA, DIA + dt.timedelta(days=1)}
    conteo, _ = lecturas_service.guardar_meteo(db, fundo, lecturas, origen=OrigenMeteo.excel_historico,
                                               corrida_id=None)
    assert (conteo.nuevas, conteo.actualizadas, conteo.omitidas) == (0, 0, 48)

    api = lecturas.copy()
    api["T"] = 33.3
    conteo, _ = lecturas_service.guardar_meteo(db, fundo, api, origen=OrigenMeteo.weatherlink, corrida_id=None)
    assert (conteo.nuevas, conteo.actualizadas, conteo.omitidas) == (0, 0, 48)
    assert db.scalar(select(func.max(MeteoLectura.temp))) < 33

    corregido = lecturas.copy()
    corregido.loc[0, "T"] = 25.0          # un Excel histórico corregido sí actualiza
    conteo, _ = lecturas_service.guardar_meteo(db, fundo, corregido, origen=OrigenMeteo.excel_historico,
                                               corrida_id=None)
    assert (conteo.nuevas, conteo.actualizadas) == (0, 1)


def _ambiente_riego_ml(lecturas, horario, planta, imagenes):
    meteo, _ = meteo_diaria(lecturas)
    phytech = resumir_phytech(horario, planta, PROJECT)
    ndvi = ndvi_diario(imagenes, PLOT, FUNDO)
    return construir_ambiente_diario(meteo, phytech, ndvi, [FUNDO])


def test_recalcular_ambiente_igual_a_riego_ml(db, fundo):
    lecturas, horario, planta = _lecturas(), _horario(), _planta()
    imagenes = pd.concat([_imagenes(DIA), _imagenes(DIA + dt.timedelta(days=5), "img-2")])
    lecturas_service.guardar_meteo(db, fundo, lecturas, origen=OrigenMeteo.excel_historico, corrida_id=None)
    lecturas_service.guardar_suelo(db, fundo, horario, corrida_id=None)
    lecturas_service.guardar_planta(db, fundo, planta, corrida_id=None)
    lecturas_service.guardar_ndvi(db, fundo, imagenes, area_id=12537, plot_id=PLOT, corrida_id=None)

    dias = [DIA + dt.timedelta(days=i) for i in range(7)]
    resultado = ambiente_service.recalcular(db, fundo, dias, project_id=PROJECT, plot_id=PLOT)
    # 02/01 completo, 03/01 solo la lectura de las 00:00, 07/01 solo NDVI; el resto sin datos.
    assert (resultado.dias, resultado.nuevas) == (7, 3)

    desde_bd = ambiente_service.ambiente_para_modelo(db, fundo).set_index("Fecha")
    esperado = _ambiente_riego_ml(lecturas, horario, planta, imagenes).set_index("Fecha")
    for fecha in (pd.Timestamp(DIA), pd.Timestamp(DIA + dt.timedelta(days=1))):
        pd.testing.assert_series_equal(
            desde_bd.loc[fecha, columnas_ambiente()].astype(float),
            esperado.loc[fecha, columnas_ambiente()].astype(float), check_names=False,
        )
    solo_ndvi = desde_bd.loc[pd.Timestamp(DIA + dt.timedelta(days=5))]
    assert solo_ndvi["ndvi_medio"] == 0.25
    assert (solo_ndvi[["tiene_meteo", "tiene_suelo", "tiene_planta"]] == 0).all()
    assert desde_bd.loc[pd.Timestamp(DIA), ["tiene_meteo", "tiene_suelo", "tiene_planta"]].tolist() == [1, 1, 1]

    # Repetir no cambia nada.
    otra = ambiente_service.recalcular(db, fundo, dias, project_id=PROJECT, plot_id=PLOT)
    assert (otra.nuevas, otra.actualizadas, otra.sin_cambios) == (0, 0, 3)


def test_recalcular_borra_dias_que_quedaron_sin_datos_y_respeta_hoy(db, fundo):
    db.add(AmbienteDiario(fundo_id=fundo.id, fecha=DIA, t_media=1.0, tiene_meteo=1))
    db.flush()
    resultado = ambiente_service.recalcular(db, fundo, [DIA], project_id=PROJECT, plot_id=PLOT)
    assert resultado.borradas == 1

    # 23:30 del 09/03 en Lima = 04:30 del 10/03 en UTC: el 09/03 (hoy en Lima) no se calcula.
    with time_machine.travel(dt.datetime(2025, 3, 10, 4, 30, tzinfo=dt.UTC), tick=False):
        for dia in (dt.date(2025, 3, 8), dt.date(2025, 3, 9)):
            lecturas_service.guardar_meteo(db, fundo, _lecturas(dia, n=47),
                                           origen=OrigenMeteo.excel_historico, corrida_id=None)
        resultado = ambiente_service.recalcular(db, fundo, [dt.date(2025, 3, 8), dt.date(2025, 3, 9)])
    assert resultado.dias == 1 and resultado.nuevas == 1
    assert [a.fecha for a in repo.ambiente(db, fundo.id)] == [dt.date(2025, 3, 8)]


def _ciclos_crudos(filas):
    """Filas (fecha, turno, inicio_min, duracion, m3, m3ha) con el formato de leer_riego."""
    df = pd.DataFrame(filas, columns=["Fecha", "Turno", "inicio_min", "duracion_min", "riego_m3", "riego_m3ha"])
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    df["Fundo"], df["Modulo"] = FUNDO, "EN01-MOD5"
    df["Valvula"] = df["Turno"].map({"TE01": 6061000, "TE02": 6263000})
    df["fin_min"] = df["inicio_min"] + df["duracion_min"]
    df["hora_inicio"] = df["inicio_min"].map(lambda m: f"{int(m) // 60 % 24:02d}:{int(m) % 60:02d}")
    df["hora_fin"] = df["fin_min"].map(lambda m: f"{int(m) // 60 % 24:02d}:{int(m) % 60:02d}")
    df["fin_dia_siguiente"] = (df["fin_min"] >= 1440).astype(int)
    df["area_ha"] = df["riego_m3"] / df["riego_m3ha"]
    for c in ("Fundo", "Modulo", "Turno"):
        df[c] = df[c].astype("string")
    return df[COLUMNAS_RIEGO]


CRUDOS = [
    ("2025-01-02", "TE01", 300.0, 60.0, 390.57, 30.0),
    ("2025-01-02", "TE01", 1400.0, 90.0, 390.57, 30.0),   # termina al día siguiente
    ("2025-01-02", "TE01", 900.0, 2.0, 5.0, 0.4),         # apertura fallida
    ("2025-01-02", "TE02", 300.0, 45.0, 252.98, 20.0),
    ("2025-01-02", "TE02", 300.0, 45.0, 252.98, 20.0),    # duplicado
    ("2025-01-03", "TE01", 420.0, 50.0, 325.48, 25.0),
    ("2025-01-03", "TE02", 100.0, 1.0, 0.0, 0.0),         # solo fallidas: sin registro
]


def test_carga_de_riego_idempotente_y_reemplazo(db, modulo):
    resultado = ResultadoFuente("riego")
    carga_historica.cargar_riego(db, modulo, _ciclos_crudos(CRUDOS), resultado)
    assert (resultado.filas, resultado.nuevas, resultado.omitidas, resultado.conflictos) == (3, 3, 0, 0)
    assert db.scalar(select(func.count()).select_from(RiegoCiclo)) == 4
    registro = db.scalars(select(RiegoRegistro).where(RiegoRegistro.fecha == DIA,
                                                      RiegoRegistro.turno_id == 1)).one()
    assert registro.estado.value == "aplicado" and registro.origen.value == "historico"
    assert [c.inicio_min for c in registro.ciclos] == [300.0, 1400.0]
    assert registro.ciclos[1].fin_dia_siguiente is True and registro.ciclos[0].valvula == "6061000"
    assert registro.contenido_sha256 == hash_contenido(
        [{"inicio_min": c.inicio_min, "duracion_min": c.duracion_min, "riego_m3": c.riego_m3,
          "riego_m3ha": c.riego_m3ha, "valvula": c.valvula} for c in registro.ciclos])

    otra = ResultadoFuente("riego")
    carga_historica.cargar_riego(db, modulo, _ciclos_crudos(CRUDOS), otra)
    assert (otra.nuevas, otra.actualizadas, otra.omitidas, otra.conflictos) == (0, 0, 3, 0)

    cambiados = [list(f) for f in CRUDOS]
    cambiados[0][4] = 400.0
    conflicto = ResultadoFuente("riego")
    carga_historica.cargar_riego(db, modulo, _ciclos_crudos(cambiados), conflicto)
    assert (conflicto.nuevas, conflicto.conflictos) == (0, 1)

    reemplazo = ResultadoFuente("riego")
    carga_historica.cargar_riego(db, modulo, _ciclos_crudos(cambiados), reemplazo, reemplazar=True)
    assert (reemplazo.nuevas, reemplazo.actualizadas, reemplazo.omitidas) == (0, 1, 2)
    versiones = db.scalars(select(RiegoRegistro).where(RiegoRegistro.fecha == DIA, RiegoRegistro.turno_id == 1)
                           .order_by(RiegoRegistro.version)).all()
    assert [(v.version, v.vigente) for v in versiones] == [(1, False), (2, True)]
    assert versiones[1].basado_en_id == versiones[0].id


def test_carga_de_riego_omite_fechas_de_hoy_y_turnos_desconocidos(db, modulo):
    filas = [("2025-01-02", "TE09", 300.0, 60.0, 390.0, 30.0)]
    resultado = ResultadoFuente("riego")
    with time_machine.travel(dt.datetime(2025, 1, 2, 15, 0, tzinfo=dt.UTC), tick=False):
        carga_historica.cargar_riego(db, modulo, _ciclos_crudos(CRUDOS[:1] + filas), resultado)
    assert resultado.nuevas == 0
    assert any("hoy o posterior" in m for m in resultado.mensajes)


def test_historial_desde_la_bd_igual_al_de_los_ciclos(db, fundo, modulo):
    crudos = _ciclos_crudos(CRUDOS)
    carga_historica.cargar_riego(db, modulo, crudos, ResultadoFuente("riego"))
    lecturas_service.guardar_meteo(db, fundo, _lecturas(), origen=OrigenMeteo.excel_historico, corrida_id=None)
    ambiente_service.recalcular(db, fundo, [DIA], project_id=PROJECT, plot_id=PLOT)

    historial = construir_historial(db, modulo.id).historial
    esperados, _, _ = limpiar_ciclos(crudos, 5.0, 2.0)
    pd.testing.assert_frame_equal(historial.ciclos, esperados, check_dtype=False)
    pd.testing.assert_frame_equal(historial.turno_dia, tabla_turno_dia(esperados), check_dtype=False)
    assert historial.ambiente["Fundo"].tolist() == [FUNDO]
    assert set(historial.ciclos["Fundo"]) == {FUNDO}   # mismo texto que el ambiente

    # Con fecha a planificar: solo lo anterior.
    previo = construir_historial(db, modulo.id, hasta=DIA + dt.timedelta(days=1)).historial
    assert set(previo.ciclos["Fecha"].dt.date) == {DIA}


def test_historial_usa_el_cronograma_si_falta_el_registro(db, modulo):
    """Turno-día sin registro: ciclos de la versión publicada del cronograma de ese día."""
    carga_historica.cargar_riego(db, modulo, _ciclos_crudos(CRUDOS[:1]), ResultadoFuente("riego"))
    cronograma = Cronograma(modulo_id=modulo.id, fecha=DIA)
    db.add(cronograma)
    db.flush()
    version = CronogramaVersion(cronograma_id=cronograma.id, numero=1, origen=OrigenVersion.modelo)
    db.add(version)
    db.flush()
    for turno_id, inicio in ((1, 600.0), (2, 480.0)):   # TE01 ya tiene registro: se ignora
        db.add(CronogramaCiclo(version_id=version.id, turno_id=turno_id, ciclo=1, riego_m3ha=20.0,
                               riego_m3=253.0, duracion_min=40.0, inicio_min=inicio,
                               fin_min=inicio + 40, hora_inicio="08:00", hora_fin="08:40"))
    cronograma.borrador_version_id = version.id
    db.flush()

    resultado = construir_historial(db, modulo.id, hasta=DIA + dt.timedelta(days=1))
    assert resultado.turno_dias_cronograma == [(DIA, "TE02")]
    te02 = resultado.historial.ciclos[resultado.historial.ciclos["Turno"] == "TE02"]
    assert te02["inicio_min"].tolist() == [480.0]
    # Sin fecha a planificar no se mira el cronograma.
    assert construir_historial(db, modulo.id).turno_dias_cronograma == []


def test_carga_historica_registra_corridas_y_aisla_errores(db, tmp_path):
    rutas = carga_historica.RutasHistorico(meteo=tmp_path / "no.xlsx", phytech=tmp_path / "no.xlsx",
                                           ndvi=tmp_path, riego=tmp_path / "no.xlsx")
    resultado = carga_historica.cargar_historico(db, rutas, fuentes=("meteo", "ndvi"))
    assert [f.estado for f in resultado.fuentes] == ["error", "error"]
    assert resultado.con_error
    from app.models import IngestaCorrida

    corridas = db.scalars(select(IngestaCorrida).order_by(IngestaCorrida.id)).all()
    assert [c.fuente for c in corridas][-2:] == ["historico_meteo", "historico_ndvi"]
    assert all(c.estado.value == "error" and c.errores and c.fin_at for c in corridas[-2:])
