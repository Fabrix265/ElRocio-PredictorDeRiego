"""Paridad ida y vuelta con los archivos reales (H1, §2.3): cargar ``ml/data/raw`` a la BD con
``cargar-historico``, leer de la BD y comparar con lo que ``riego_ml`` arma desde los archivos.

- ``ambiente_diario`` recalculado desde la BD = ``unir_fuentes(...).ambiente_diario`` (días con
  datos; los días vacíos del calendario no se guardan).
- ``Historial`` desde la BD = ``Historial`` en memoria desde los archivos (ciclos, turno-día y
  ambiente).
- Si está el modelo entrenado, el plan del día siguiente al último riego es idéntico.
- WeatherLink: un mes de la API (``WeatherLink/completo``, nov-2021, posterior al cambio de corte de
  día del Excel) pasado por ``conversion`` y guardado, empalmado con el Excel, da el mismo clima
  diario que ``data_metereologica.xlsx``.

Tolerancia del ambiente: 0,001 (una unidad del ``round(3)`` de ``meteo_diaria``). El promedio
diario de pandas (``groupby().mean()``) puede diferir en el último bit según cuántos días tenga
el DataFrame, y en un empate (p. ej. 23,2625) eso cambia el redondeo: pasa también dentro de
``riego_ml`` si se lee un archivo con otro rango de fechas. Se exige además que esos casos sean
muy pocos y que el plan sea idéntico.

Se salta si faltan los archivos (``ml/data`` no está en git). Carga todo una vez por módulo, dentro
de una transacción que se deshace al final; cada Excel se lee una sola vez.
"""

from __future__ import annotations

import functools
import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from riego_ml.config import load_config
from riego_ml.dataset.limpieza import limpiar_ciclos, tabla_turno_dia
from riego_ml.dataset.preparar import Historial
from riego_ml.dataset.unir import columnas_ambiente, unir_fuentes
from riego_ml.sources.meteo import COLUMNAS_DIARIAS, leer_meteo, meteo_diaria
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.integraciones.weatherlink import conversion
from app.ml.historial_bd import construir_historial
from app.models import AmbienteDiario, MeteoLectura
from app.models.enums import OrigenMeteo
from app.repositories import datos_campo as repo
from app.services import ambiente_service, ingesta_service, lecturas_service
from app.services.carga_historica import CODIGO_MODULO, RutasHistorico, cargar_historico

RUTAS = RutasHistorico.por_defecto()
pytestmark = pytest.mark.skipif(
    not all(r.exists() for r in (RUTAS.meteo, RUTAS.phytech, RUTAS.ndvi, RUTAS.riego)),
    reason="faltan los archivos de ml/data/raw",
)
BANDERAS = ["tiene_meteo", "tiene_suelo", "tiene_planta"]
TOLERANCIA = 0.001 + 1e-9
MAX_INEXACTOS = 0.001  # fracción de valores del ambiente con diferencia de redondeo


CACHE_EXCEL = Path(__file__).resolve().parents[1] / "var" / "cache_pruebas"


@pytest.fixture(scope="module", autouse=True)
def excel_una_vez():
    """La carga a la BD y unir_fuentes leen los mismos Excel: cada uno se lee una sola vez (y
    queda en ``backend/var/cache_pruebas``, ignorado por git, mientras el archivo no cambie:
    openpyxl tarda minutos en leer el histórico completo)."""
    original = pd.read_excel

    @functools.lru_cache(maxsize=None)
    def _leer(ruta: str, clave: tuple) -> pd.DataFrame:
        info = Path(ruta).stat()
        firma = hashlib.sha256(repr((ruta, info.st_size, info.st_mtime_ns, clave)).encode()).hexdigest()
        cache = CACHE_EXCEL / f"{firma[:32]}.pkl"
        if cache.exists():
            return pd.read_pickle(cache)  # escrito por esta misma prueba
        df = original(ruta, **dict(clave))
        CACHE_EXCEL.mkdir(parents=True, exist_ok=True)
        df.to_pickle(cache)
        return df

    def leer(ruta, *args, **kwargs):
        if args or not isinstance(ruta, (str, Path)):
            return original(ruta, *args, **kwargs)
        return _leer(str(ruta), tuple(sorted(kwargs.items()))).copy()

    with pytest.MonkeyPatch.context() as parche:
        parche.setattr(pd, "read_excel", leer)
        yield


@pytest.fixture(scope="module")
def bd(engine):
    """Sesión con privilegios de riego_app y todo el histórico cargado (se deshace al final)."""
    with engine.connect() as conexion:
        transaccion = conexion.begin()
        conexion.exec_driver_sql("SET LOCAL ROLE riego_app")
        sesion = Session(bind=conexion, join_transaction_mode="create_savepoint", autoflush=False,
                         expire_on_commit=False)
        resultado = cargar_historico(sesion, RUTAS)
        try:
            yield sesion, resultado
        finally:
            sesion.close()
            transaccion.rollback()


@pytest.fixture(scope="module")
def archivos():
    """Lo que riego_ml arma desde los archivos (misma ruta que unir_datos + cargar_historial)."""
    config = load_config()
    rutas, fuentes = config.rutas, config.fuentes
    unido = unir_fuentes(
        rutas.riego, rutas.meteo, rutas.phytech, hoja_riego=fuentes.hoja_riego,
        phytech_project_id=fuentes.phytech_project_id, carpeta_phytech_crudo=rutas.phytech_crudo,
        phytech_area_id=fuentes.phytech_area_id, phytech_plot_id=fuentes.phytech_plot_id,
    )
    prep = config.preparacion
    ciclos, descartados, diag = limpiar_ciclos(unido.riego_unido, prep.min_duracion_min, prep.min_riego_m3ha)
    historial = Historial(ciclos, tabla_turno_dia(ciclos), unido.ambiente_diario, descartados, diag)
    return config, historial


def _con_datos(ambiente: pd.DataFrame) -> pd.DataFrame:
    hay = ambiente[columnas_ambiente()].notna().any(axis=1) | (ambiente[BANDERAS] == 1).any(axis=1)
    return ambiente[hay].sort_values("Fecha").reset_index(drop=True)


def _comparar_ambiente(desde_bd: pd.DataFrame, desde_archivos: pd.DataFrame) -> None:
    a = _con_datos(desde_bd)
    b = _con_datos(desde_archivos)
    assert a["Fecha"].tolist() == b["Fecha"].tolist()
    assert a["Fundo"].astype(str).tolist() == b["Fundo"].astype(str).tolist()
    valores_a = a[columnas_ambiente()].astype(float)
    valores_b = b[columnas_ambiente()].astype(float)
    pd.testing.assert_frame_equal(valores_a, valores_b, check_exact=False, rtol=0, atol=TOLERANCIA)
    inexactos = ~np.isclose(valores_a, valores_b, rtol=0, atol=1e-9, equal_nan=True)
    assert inexactos.mean() < MAX_INEXACTOS, int(inexactos.sum())
    assert (a[BANDERAS].astype(int).to_numpy() == b[BANDERAS].astype(int).to_numpy()).all()


def test_carga_historica_sin_errores_ni_conflictos(bd):
    _, resultado = bd
    assert [f.fuente for f in resultado.fuentes] == ["meteo", "phytech", "ndvi", "riego"]
    for fuente in resultado.fuentes:
        assert fuente.estado == "ok", (fuente.fuente, fuente.mensajes)
        assert fuente.nuevas > 0 and fuente.conflictos == 0
    assert resultado.ambiente.nuevas > 2000


def test_ambiente_desde_la_bd_igual_al_de_los_archivos(bd, archivos):
    db, _ = bd
    _, historial = archivos
    fundo = repo.fundo_por_id(db, repo.modulo_por_codigo(db, CODIGO_MODULO).fundo_id)
    _comparar_ambiente(ambiente_service.ambiente_para_modelo(db, fundo), historial.ambiente)


def test_historial_desde_la_bd_igual_al_de_los_archivos(bd, archivos):
    db, _ = bd
    _, esperado = archivos
    modulo = repo.modulo_por_codigo(db, CODIGO_MODULO)
    historial = construir_historial(db, modulo.id).historial
    pd.testing.assert_frame_equal(historial.ciclos, esperado.ciclos, check_dtype=False,
                                  check_exact=False, rtol=0, atol=1e-9)
    pd.testing.assert_frame_equal(historial.turno_dia, esperado.turno_dia, check_dtype=False,
                                  check_exact=False, rtol=0, atol=1e-9)
    _comparar_ambiente(historial.ambiente, esperado.ambiente)


def test_plan_desde_la_bd_igual_al_de_los_archivos(bd, archivos):
    """H1: armar el Historial desde la BD da la misma predicción que la ruta por archivos."""
    config, esperado = archivos
    modelo = config.rutas.modelos_dir / "plan_riego" / "actual" / "modelo_plan_riego.joblib"
    if not modelo.exists():
        pytest.skip("sin modelo entrenado en ml/models")
    from riego_ml.modeling.prediccion import cargar_plan, planificar

    db, _ = bd
    plan = cargar_plan(config, modelo)
    historial = construir_historial(db, repo.modulo_por_codigo(db, CODIGO_MODULO).id).historial
    fecha = esperado.ciclos["Fecha"].max() + pd.Timedelta(days=1)
    desde_bd = planificar(plan, historial, [fecha], config)
    desde_archivos = planificar(plan, esperado, [fecha], config)
    assert len(desde_bd) >= 5
    pd.testing.assert_frame_equal(desde_bd, desde_archivos, check_dtype=False)


WL_2021 = RUTAS.meteo.parent / "WeatherLink" / "completo" / (
    "Historic_tipo24-Vantage-Pro2-Plus-Cabled_ds4_2021_est28494.xlsx"
)
MES_WL = (pd.Timestamp("2021-11-01"), pd.Timestamp("2021-11-30"))
FIN_EXCEL = pd.Timestamp("2021-11-15")      # el Excel cubre del 01 al 15 ...
INICIO_WL = pd.Timestamp("2021-11-14")      # ... y WeatherLink del 14 al 30: dos días solapados
EXACTAS = ["T_media", "T_min", "HR_media", "Viento_media", "meteo_lecturas"]


@pytest.fixture
def bd_clima_weatherlink(bd):
    """Usa la conexión histórica en un SAVEPOINT limpio: otra conexión quedaría esperando los
    bloqueos de la fixture de módulo. Al terminar restaura todos los datos de esa fixture."""
    sesion, _ = bd
    transaccion = sesion.begin_nested()
    try:
        sesion.execute(delete(AmbienteDiario))
        sesion.execute(delete(MeteoLectura))
        yield sesion
    finally:
        transaccion.rollback()


@pytest.mark.skipif(not WL_2021.exists(), reason="sin ml/data/raw/WeatherLink/completo")
def test_clima_desde_weatherlink_igual_al_del_excel(bd_clima_weatherlink):
    """Detecta un corrimiento del corte de día (la lectura de las 24:00) o de las fórmulas: cada día
    armado desde la BD con lecturas de WeatherLink (y el empalme con el Excel, sin lecturas
    repetidas) da el mismo ``meteo_diaria`` que el Excel de entrenamiento."""
    db = bd_clima_weatherlink
    fundo = repo.fundo_por_id(db, repo.modulo_por_codigo(db, CODIGO_MODULO).fundo_id)
    excel, _ = leer_meteo(RUTAS.meteo)
    dia_excel = excel["fecha_hora"].dt.normalize()
    esperado, _ = meteo_diaria(excel[dia_excel.between(*MES_WL)])

    tramo_excel = excel[dia_excel.between(MES_WL[0], FIN_EXCEL)]
    lecturas_service.guardar_meteo(db, fundo, tramo_excel, origen=OrigenMeteo.excel_historico, corrida_id=None)
    registros = [
        r for r in pd.read_excel(WL_2021).to_dict("records")
        if (dia := conversion.dia_de_registro(r)) is not None and INICIO_WL <= pd.Timestamp(dia) <= MES_WL[1]
    ]
    resultado = ingesta_service.ResultadoFuente()
    ingesta_service.guardar_lecturas_weatherlink(db, fundo, registros, None, resultado)
    assert resultado.conteo.omitidas > 90  # el solape (14 y 15) no pisa el Excel
    dias = pd.date_range(*MES_WL).date
    ambiente_service.recalcular(db, fundo, dias)

    desde_bd = ambiente_service.ambiente_para_modelo(db, fundo)
    desde_bd = desde_bd[desde_bd["Fecha"].between(*MES_WL)].reset_index(drop=True)
    assert desde_bd["Fecha"].tolist() == esperado["Fecha"].tolist() and len(desde_bd) == 30
    # Ningún día con lecturas de más ni de menos (la misma lectura no cae en dos días).
    por_dia = pd.Series([f.date() for f in db.scalars(
        select(MeteoLectura.fecha_hora).where(MeteoLectura.fundo_id == fundo.id))]).value_counts()
    assert (por_dia.sort_index().to_numpy() == esperado["meteo_lecturas"].to_numpy()).all()
    pd.testing.assert_frame_equal(desde_bd[EXACTAS].astype(float), esperado[EXACTAS].astype(float),
                                  check_exact=False, rtol=0, atol=1e-9)
    pd.testing.assert_frame_equal(desde_bd[COLUMNAS_DIARIAS].astype(float),
                                  esperado[COLUMNAS_DIARIAS].astype(float), check_exact=False, rtol=0,
                                  atol=TOLERANCIA)
