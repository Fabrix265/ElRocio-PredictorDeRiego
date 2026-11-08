"""APIs falsas de WeatherLink y Phytech para las pruebas (``httpx.MockTransport``, sin red).

Las respuestas imitan la forma de las reales (vista en ``ingesta_crudo``): WeatherLink
``{sensors: [{lsid, sensor_type, data: [...]}]}`` en °F, pulgadas y millas; Phytech JSON anidado
``area → plot → project → fecha [→ hora]`` y NDVI en un ZIP con ``*_histogram.json``.
Las claves de prueba son valores reconocibles para comprobar que nunca se guardan ni se registran.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.tiempo import zona_lima
from app.integraciones.http import Reintentos
from app.integraciones.phytech.cliente import ClientePhytech
from app.integraciones.weatherlink.cliente import ClienteWeatherLink

WL_KEY = "wl-clave-secreta-0001"
WL_SECRET = "wl-secreto-ultra-0002"
PH_KEY = "ph-clave-secreta-0003"
PH_SECRET = "ph-secreto-ultra-0004"
SECRETOS = (WL_KEY, WL_SECRET, PH_KEY, PH_SECRET)

AREA = 12537
PLOT = 70208
PROJECT = 907557
OTRO_PLOT = 63915
OTRO_PROJECT = 907517
ESTACION = 28494

WL_BASE = "https://api.weatherlink.test/v2"
PH_BASE = "https://api.phytech.test"


def sin_espera() -> Reintentos:
    return Reintentos(dormir=lambda _s: None)


# --- WeatherLink ----------------------------------------------------------------

def registro_wl(ts: int, *, temp_f: float = 77.0, hum: int = 70, et: float = 0.004,
                wind_run: float = 0.5, rain_mm: float = 0.0, rad: int = 300) -> dict[str, Any]:
    return {
        "ts": ts, "temp_out": temp_f, "temp_out_hi": temp_f + 0.5, "temp_out_lo": temp_f - 0.5,
        "hum_out": hum, "solar_rad_hi": rad, "et": et, "wind_run": wind_run, "rainfall_mm": rain_mm,
        "rainfall_in": rain_mm / 25.4, "bar": 29.8, "tz_offset": -18000,
    }


def dia_wl(dia: dt.date, **kwargs: Any) -> list[dict[str, Any]]:
    """48 registros: ``ts`` = fin de intervalo, de 00:30 a 24:00 de Lima (lo que devuelve la API
    para ``(D 00:00, D+1 00:00]``; el de las 24:00 se guarda como ``D 00:00``)."""
    inicio = int(dt.datetime.combine(dia, dt.time(), tzinfo=zona_lima()).timestamp())
    return [registro_wl(inicio + 1800 * (k + 1), **kwargs) for k in range(48)]


def payload_wl(registros: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "station_id": ESTACION, "generated_at": 1794119936,
        "sensors": [
            {"lsid": 1, "sensor_type": 504, "data_structure_type": 15, "data": [{"ts": 1, "bar": 29.8}]},
            {"lsid": 90614, "sensor_type": 24, "data_structure_type": 4, "data": registros},
        ],
    }


# --- Phytech --------------------------------------------------------------------

def _dias(desde: dt.date, hasta: dt.date) -> list[dt.date]:
    return [desde + dt.timedelta(days=i) for i in range((hasta - desde).days + 1)]


def hora_suelo(humedad: float | None, *, temp: float | None = None) -> dict[str, Any]:
    """Una hora de ``SoilHourlyData``. Sin ``humedad``: hora de relleno (todo ``null``) o, con
    ``temp``, una hora que solo trae temperatura."""
    if humedad is None:
        return {p: {"temp": temp, "moisture": None, "pressure": None} for p in ("15", "30", "45", "60", "75", "90")} | {
            "rootZone": {"moisture": None, "saturation": None, "stressline": None, "rootZoneNormalized": None}}
    capas = {p: {"temp": 26.5, "moisture": humedad - i, "pressure": None}
             for i, p in enumerate(("15", "30", "45", "60", "75", "90"))}
    return capas | {"rootZone": {"safety": 29.0, "moisture": humedad - 1, "saturation": 36.17,
                                 "stressline": 29.0, "rootZoneNormalized": 90.0}}


def payload_suelo(desde: dt.date, hasta: dt.date, humedad: Callable[[dt.date, int], float | None]) -> dict:
    por_dia = {
        d.isoformat(): {f"{h:02d}:00": hora_suelo(humedad(d, h)) for h in range(24)}
        for d in _dias(desde, hasta)
    }
    return {str(AREA): {str(PLOT): {str(PROJECT): por_dia},
                        str(OTRO_PLOT): {str(OTRO_PROJECT): por_dia}}}


def payload_planta(desde: dt.date, hasta: dt.date) -> dict:
    por_dia = {d.isoformat(): {"ET": 4.3, "ps": 50.0, "mds": 240.0, "rain": 0.0, "growth": 2.0,
                               "fruit size": None, "fruit growth": None} for d in _dias(desde, hasta)}
    return {str(AREA): {str(PLOT): {str(PROJECT): por_dia}}}


def payload_pronostico(hoy: dt.date) -> dict:
    por_dia = {(hoy + dt.timedelta(days=i)).isoformat():
               {"et0": 3.4, "etc": None, "humidity": 80.5, "max_temperature": 29.0} for i in range(1, 4)}
    return {str(AREA): {str(PLOT): {str(PROJECT): por_dia}}}


def zip_ndvi(fechas: list[dt.date]) -> bytes:
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w") as archivo:
        archivo.writestr("manifest.json", json.dumps({"area_id": AREA, "images_count": len(fechas)}))
        for i, fecha in enumerate(fechas):
            histograma = {
                "image_id": f"img-{fecha.isoformat()}", "date": fecha.isoformat(), "entity_type": "plot",
                "entity_id": PLOT, "no_vegetation": False,
                "classes": [{"class": k, "color": f"#00{k}", "ndvi_min": k * 0.2, "ndvi_max": k * 0.2 + 0.2,
                             "percent": 20.0} for k in range(5)],
                "legend": [], "histogram": {"0.1": 3},
            }
            archivo.writestr(f"img{i}_histogram.json", json.dumps(histograma))
            archivo.writestr(f"img{i}.png", b"\x89PNG")
    return memoria.getvalue()


# --- Servidor falso -------------------------------------------------------------

@dataclass
class ApisFalsas:
    """Responde como las APIs y registra cada petición. Se puede programar fallas por ruta."""

    humedad: Callable[[dt.date, int], float | None] = lambda _d, h: 30.0 + h / 10
    wl_registros: Callable[[dt.date], list[dict[str, Any]]] = dia_wl
    ndvi_fechas: list[dt.date] = field(default_factory=list)
    fallas: dict[str, list[int]] = field(default_factory=dict)  # ruta -> estados a devolver antes del OK
    token_n: int = 0
    tokens_revocados: set[str] = field(default_factory=set)
    peticiones: list[httpx.Request] = field(default_factory=list)
    hoy: dt.date = dt.date(2026, 11, 8)

    def conteo(self) -> Counter:
        return Counter(r.url.path for r in self.peticiones)

    def _falla(self, ruta: str) -> httpx.Response | None:
        pendientes = self.fallas.get(ruta)
        if pendientes:
            return httpx.Response(pendientes.pop(0), text=f"falla programada {ruta}")
        return None

    def __call__(self, peticion: httpx.Request) -> httpx.Response:
        self.peticiones.append(peticion)
        ruta = peticion.url.path
        falla = self._falla(ruta)
        if falla is not None:
            return falla
        params = peticion.url.params
        if ruta.startswith("/v2/historic/"):
            if params.get("api-key") != WL_KEY or peticion.headers.get("x-api-secret") != WL_SECRET:
                return httpx.Response(401, json={"message": "unauthorized"})
            inicio = int(params["start-timestamp"]) + 1
            dia = dt.datetime.fromtimestamp(inicio, zona_lima()).date()
            return httpx.Response(200, json=payload_wl(self.wl_registros(dia)))
        if ruta == "/auth/api-token":
            if peticion.headers.get("x-api-key") != PH_KEY or peticion.headers.get("x-api-secret-key") != PH_SECRET:
                return httpx.Response(401, json={"statusCode": 401})
            self.token_n += 1
            return httpx.Response(200, json={"statusCode": 200, "data": {"token": f"token-falso-{self.token_n:04d}"}})
        autorizacion = peticion.headers.get("authorization", "")
        if not autorizacion.startswith("Bearer token-falso-") or autorizacion[7:] in self.tokens_revocados:
            return httpx.Response(401, json={"statusCode": 401, "error": "token"})
        if ruta == "/api/v1/ProjectsClimateForecastData":
            return httpx.Response(200, json={"statusCode": 200, "data": payload_pronostico(self.hoy)})
        desde = dt.date.fromisoformat(params["start_date"])
        hasta = dt.date.fromisoformat(params["end_date"])
        if ruta == "/api/v1/SoilHourlyData":
            return httpx.Response(200, json={"statusCode": 200, "data": payload_suelo(desde, hasta, self.humedad)})
        if ruta == "/api/v1/ProjectsDailyData":
            return httpx.Response(200, json={"statusCode": 200, "data": payload_planta(desde, hasta)})
        if ruta == "/api/v1/NdviImages":
            fechas = [f for f in self.ndvi_fechas if desde <= f <= hasta]
            return httpx.Response(200, content=zip_ndvi(fechas), headers={"content-type": "application/zip"})
        return httpx.Response(404)

    def transporte(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def weatherlink(self, **kwargs: Any) -> ClienteWeatherLink:
        return ClienteWeatherLink(api_key=WL_KEY, api_secret=WL_SECRET, base_url=WL_BASE,
                                  station_id=ESTACION, transport=self.transporte(),
                                  reintentos=kwargs.pop("reintentos", sin_espera()), **kwargs)

    def phytech(self, **kwargs: Any) -> ClientePhytech:
        return ClientePhytech(api_key=PH_KEY, api_secret=PH_SECRET, base_url=PH_BASE,
                              transport=self.transporte(), reintentos=kwargs.pop("reintentos", sin_espera()),
                              **kwargs)
