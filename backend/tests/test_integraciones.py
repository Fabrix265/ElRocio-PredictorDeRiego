"""Clientes HTTP de WeatherLink y Phytech con transporte simulado (sin red): autenticación,
token de Phytech en memoria (renovación a las 23 h y ante un 401), reintentos con espera,
límites de rango y errores sin secretos."""

from __future__ import annotations

import datetime as dt
import logging

import httpx
import pytest

from app.integraciones.http import ErrorIntegracion, Reintentos, TipoError, ruta_sin_query
from app.integraciones.phytech import adaptador
from app.integraciones.phytech.cliente import RENOVAR_TOKEN_S, leer_zip_ndvi, tramos
from app.integraciones.weatherlink import conversion
from app.integraciones.weatherlink.cliente import rango_dia
from tests.apis_falsas import (
    PH_KEY,
    PH_SECRET,
    PLOT,
    PROJECT,
    SECRETOS,
    WL_KEY,
    WL_SECRET,
    ApisFalsas,
    sin_espera,
)

DIA = dt.date(2026, 11, 5)


def _sin_secretos(texto: str, extra: tuple[str, ...] = ()) -> None:
    for secreto in (*SECRETOS, *extra):
        assert secreto not in texto


# --- WeatherLink ----------------------------------------------------------------

def test_rango_dia_cubre_de_00_00_a_23_30_de_lima():
    inicio, fin = rango_dia(DIA)
    assert fin - inicio == 24 * 3600
    # Lima es UTC-5 sin horario de verano: 2026-11-05 00:00 Lima = 05:00 UTC.
    assert inicio + 1 == int(dt.datetime(2026, 11, 5, 5, tzinfo=dt.UTC).timestamp())


def test_weatherlink_autentica_con_query_y_cabecera_y_no_guarda_la_clave():
    apis = ApisFalsas()
    with apis.weatherlink() as cliente:
        llamada = cliente.historico_dia(DIA)
    peticion = apis.peticiones[0]
    assert peticion.url.path == "/v2/historic/28494"
    assert peticion.url.params["api-key"] == WL_KEY
    assert peticion.headers["x-api-secret"] == WL_SECRET
    assert llamada.endpoint == "historic/28494"
    assert llamada.parametros["dia"] == "2026-11-05"
    _sin_secretos(str(llamada.parametros))
    registros = conversion.registros_de_payload(llamada.payload)
    assert len(registros) == 48  # solo el sensor de la consola (el barómetro no trae los campos)
    horas = [conversion.fecha_hora_local(r["ts"]) for r in registros]
    assert str(horas[0]) == "2026-11-05 00:00:00" and str(horas[-1]) == "2026-11-05 23:30:00"


def test_weatherlink_credenciales_invalidas_sin_reintentar_y_sin_query_en_el_error():
    apis = ApisFalsas()
    from app.integraciones.weatherlink.cliente import ClienteWeatherLink

    with ClienteWeatherLink(api_key="otra-clave-mala-99", api_secret=WL_SECRET, base_url="https://api.weatherlink.test/v2",
                            station_id=28494, transport=apis.transporte(), reintentos=sin_espera()) as cliente:
        with pytest.raises(ErrorIntegracion) as error:
            cliente.historico_dia(DIA)
    assert error.value.tipo == TipoError.CREDENCIALES and error.value.status_code == 401
    assert error.value.endpoint == "/v2/historic/28494"
    assert len(apis.peticiones) == 1
    _sin_secretos(str(error.value.como_dict()), ("otra-clave-mala-99",))


def test_weatherlink_reintenta_429_y_5xx_con_espera_creciente():
    esperas: list[float] = []
    apis = ApisFalsas(fallas={"/v2/historic/28494": [429, 503]})
    reintentos = Reintentos(dormir=esperas.append)
    with apis.weatherlink(reintentos=reintentos) as cliente:
        cliente.historico_dia(DIA)
    assert len(apis.peticiones) == 3
    assert esperas == [10.0, 10.0]  # 429: 10 s × intento 1; 5xx: 5 s × intento 2


def test_reintentos_respetan_retry_after_con_tope_y_se_agotan():
    esperas: list[float] = []

    def siempre_429(_peticion: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "500"})

    reintentos = Reintentos(max_intentos=3, dormir=esperas.append)
    with httpx.Client(transport=httpx.MockTransport(siempre_429)) as cliente:
        with pytest.raises(ErrorIntegracion) as error:
            reintentos.get(cliente, f"https://x.test/v2/historic/1?api-key={WL_KEY}")
    assert esperas == [60.0, 60.0]  # Retry-After con tope de 60 s, sin esperar tras el último
    assert error.value.tipo == TipoError.REINTENTOS and error.value.status_code == 429
    assert error.value.endpoint == "/v2/historic/1"
    _sin_secretos(str(error.value.como_dict()))


def test_reintentos_ante_errores_de_red():
    intentos = {"n": 0}

    def red_intermitente(peticion: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        if intentos["n"] < 3:
            raise httpx.ConnectError(f"sin conexión a {peticion.url}")
        return httpx.Response(200, json={"ok": True})

    esperas: list[float] = []
    with httpx.Client(transport=httpx.MockTransport(red_intermitente)) as cliente:
        respuesta = Reintentos(dormir=esperas.append).get(cliente, f"https://x.test/a?api-key={WL_KEY}")
    assert respuesta.status_code == 200 and esperas == [2.0, 4.0]

    def red_caida(peticion: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"sin conexión a {peticion.url}")

    with httpx.Client(transport=httpx.MockTransport(red_caida)) as cliente:
        with pytest.raises(ErrorIntegracion) as error:
            Reintentos(dormir=lambda _s: None).get(cliente, f"https://x.test/a?api-key={WL_KEY}")
    assert error.value.tipo == TipoError.REINTENTOS
    _sin_secretos(str(error.value.como_dict()))  # el mensaje de httpx traía la URL con la clave


def test_ruta_sin_query():
    assert ruta_sin_query(f"https://api.weatherlink.com/v2/historic/28494?api-key={WL_KEY}") == "/v2/historic/28494"


# --- Phytech: token -------------------------------------------------------------

def test_phytech_pide_el_token_una_vez_y_lo_reutiliza():
    apis = ApisFalsas()
    with apis.phytech() as cliente:
        cliente.planta_diaria(12537, DIA, DIA)
        cliente.pronostico(12537)
        assert cliente.renovaciones == 1
    token_pedido = apis.peticiones[0]
    assert token_pedido.method == "POST" and token_pedido.url.path == "/auth/api-token"
    assert token_pedido.headers["x-api-key"] == PH_KEY and token_pedido.headers["x-api-secret-key"] == PH_SECRET
    assert apis.peticiones[1].headers["authorization"] == "Bearer token-falso-0001"
    assert "x-api-key" not in apis.peticiones[1].headers  # las claves solo van al pedir el token


def test_phytech_renueva_el_token_a_las_23_horas():
    reloj = {"t": 1000.0}
    apis = ApisFalsas()
    with apis.phytech(reloj=lambda: reloj["t"]) as cliente:
        cliente.pronostico(12537)
        reloj["t"] += RENOVAR_TOKEN_S - 1
        cliente.pronostico(12537)
        assert cliente.renovaciones == 1
        reloj["t"] += 2
        cliente.pronostico(12537)
        assert cliente.renovaciones == 2
    assert apis.peticiones[-1].headers["authorization"] == "Bearer token-falso-0002"


def test_phytech_ante_un_401_renueva_una_vez_y_reintenta():
    apis = ApisFalsas()
    with apis.phytech() as cliente:
        cliente.pronostico(12537)
        apis.tokens_revocados.add("token-falso-0001")  # Phytech lo revocó antes de las 24 h
        llamada = cliente.pronostico(12537)
        assert cliente.renovaciones == 2
    assert llamada.payload  # la llamada reintentada trajo datos
    rutas = [p.url.path for p in apis.peticiones]
    assert rutas == ["/auth/api-token", "/api/v1/ProjectsClimateForecastData",
                     "/api/v1/ProjectsClimateForecastData", "/auth/api-token",
                     "/api/v1/ProjectsClimateForecastData"]


def test_phytech_segundo_401_es_error_de_credenciales_sin_secretos(caplog):
    apis = ApisFalsas()
    apis.tokens_revocados.update({"token-falso-0001", "token-falso-0002"})
    caplog.set_level(logging.DEBUG)
    with apis.phytech() as cliente:
        with pytest.raises(ErrorIntegracion) as error:
            cliente.planta_diaria(12537, DIA, DIA)
        assert cliente.renovaciones == 2
    assert error.value.tipo == TipoError.CREDENCIALES and error.value.status_code == 401
    assert error.value.endpoint == "/api/v1/ProjectsDailyData"
    _sin_secretos(str(error.value.como_dict()) + caplog.text, ("token-falso-0001", "token-falso-0002"))


def test_phytech_claves_rechazadas_al_pedir_el_token():
    apis = ApisFalsas()
    from app.integraciones.phytech.cliente import ClientePhytech

    with ClientePhytech(api_key="clave-equivocada-77", api_secret=PH_SECRET, base_url="https://api.phytech.test",
                        transport=apis.transporte(), reintentos=sin_espera()) as cliente:
        with pytest.raises(ErrorIntegracion) as error:
            cliente.pronostico(12537)
    assert error.value.tipo == TipoError.CREDENCIALES and error.value.endpoint == "/auth/api-token"
    _sin_secretos(error.value.mensaje, ("clave-equivocada-77",))


def test_phytech_sin_claves_es_error_de_configuracion():
    from app.integraciones.phytech.cliente import ClientePhytech

    with pytest.raises(ErrorIntegracion) as error:
        ClientePhytech(api_key="", api_secret="", base_url="https://api.phytech.test")
    assert error.value.tipo == TipoError.CONFIGURACION


def test_phytech_reintenta_5xx_y_statuscode_distinto_de_200_es_error_de_respuesta():
    apis = ApisFalsas(fallas={"/api/v1/SoilHourlyData": [502]})
    with apis.phytech() as cliente:
        cliente.suelo_horario(12537, DIA, DIA)
    assert apis.conteo()["/api/v1/SoilHourlyData"] == 2

    def cuerpo_con_error(peticion: httpx.Request) -> httpx.Response:
        if peticion.url.path == "/auth/api-token":
            return httpx.Response(200, json={"data": {"token": "tok-abc-123"}})
        return httpx.Response(200, json={"statusCode": 400, "error": "rango inválido tok-abc-123"})

    from app.integraciones.phytech.cliente import ClientePhytech

    with ClientePhytech(api_key=PH_KEY, api_secret=PH_SECRET, base_url="https://api.phytech.test",
                        transport=httpx.MockTransport(cuerpo_con_error), reintentos=sin_espera()) as cliente:
        with pytest.raises(ErrorIntegracion) as error:
            cliente.suelo_horario(12537, DIA, DIA)
    assert error.value.tipo == TipoError.RESPUESTA and error.value.status_code == 400
    assert "tok-abc-123" not in error.value.mensaje  # el token se redacta aunque la API lo repita


# --- Phytech: rangos y adaptación -----------------------------------------------

def test_tramos_respetan_el_maximo_por_llamada():
    partes = tramos(dt.date(2026, 10, 1), dt.date(2026, 10, 16), 7)
    assert partes == [(dt.date(2026, 10, 1), dt.date(2026, 10, 7)), (dt.date(2026, 10, 8), dt.date(2026, 10, 14)),
                      (dt.date(2026, 10, 15), dt.date(2026, 10, 16))]
    apis = ApisFalsas()
    with apis.phytech() as cliente, pytest.raises(ValueError):
        cliente.suelo_horario(12537, dt.date(2026, 10, 1), dt.date(2026, 10, 8))  # 8 días > 7


def test_suelo_descarta_horas_sin_humedad_y_filtra_el_plot():
    apis = ApisFalsas(humedad=lambda _d, h: None if 10 <= h < 14 else 30.0)
    with apis.phytech() as cliente:
        llamada = cliente.suelo_horario(12537, DIA, DIA)
    crudo, sin_humedad = adaptador.suelo_crudo([llamada.payload], PLOT)
    assert len(crudo) == 20 and sin_humedad == 4
    assert set(crudo["project_id"]) == {PROJECT}  # el otro plot del área se descarta
    horario, _ = adaptador.suelo_horario([llamada.payload], PLOT, "ENSUEÑO 1")
    del_dia = horario[horario["fecha_hora"].dt.date == DIA]
    # Las horas sin humedad quedan como hueco de la rejilla horaria (hay_dato = false).
    assert len(del_dia) == 24 and int(del_dia["hay_dato_phytech"].sum()) == 20


def test_planta_y_pronostico_adaptados():
    apis = ApisFalsas()
    with apis.phytech() as cliente:
        planta = adaptador.planta_diario([cliente.planta_diaria(12537, DIA, DIA).payload], PLOT, "ENSUEÑO 1")
        pronostico = adaptador.pronostico(cliente.pronostico(12537).payload, PLOT)
    fila = planta.iloc[0]
    assert fila["mds_contraccion_um"] == 240.0 and fila["et_mm"] == 4.3 and fila["lluvia_mm"] == 0.0
    assert list(pronostico.columns) == ["project_id", "fecha", "t_max", "eto_mm", "etc_mm", "humedad"]
    assert len(pronostico) == 3 and pronostico["t_max"].iloc[0] == 29.0


def test_ndvi_lee_los_histogramas_del_zip():
    apis = ApisFalsas(ndvi_fechas=[DIA])
    with apis.phytech() as cliente:
        llamada = cliente.ndvi(12537, DIA, DIA)
    assert llamada.payload["manifest"]["images_count"] == 1
    imagenes = adaptador.imagenes_ndvi([llamada.payload])
    assert imagenes.iloc[0]["image_id"] == f"img-{DIA.isoformat()}"
    assert imagenes.iloc[0]["class4_ndvi_max"] == pytest.approx(1.0)
    with pytest.raises(ErrorIntegracion) as error:
        leer_zip_ndvi(b"PK esto no es un zip")
    assert error.value.tipo == TipoError.RESPUESTA
