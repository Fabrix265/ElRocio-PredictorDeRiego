"""Cliente de la API de Phytech (solo lectura), portado de
``ml/src/riego_ml/data_extraction/descargar_phytech.py``.

Token (H8):

- Se pide con ``POST /auth/api-token`` y las cabeceras ``X-API-KEY`` / ``X-API-SECRET-KEY``.
- Vive **solo en memoria** del cliente (nunca en la BD ni en los logs).
- Se renueva antes de vencer (Phytech lo da por 24 h; aquí a las 23 h).
- Ante un 401 se renueva **una vez** y se reintenta la llamada; un segundo 401 es un error de
  credenciales (:data:`TipoError.CREDENCIALES`).

Límites por llamada (guía de la API): suelo horario 7 días, diario agronómico 30, NDVI 10 (ZIP con
los histogramas de cada imagen); el pronóstico no lleva fechas (devuelve los próximos días). Las
funciones de rango devuelven una :class:`~app.integraciones.http.Llamada` por tramo; quien llama
decide qué hacer si un tramo falla.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import time
import zipfile
from collections.abc import Callable
from typing import Any

import httpx

from app.integraciones.http import (
    TIMEOUT,
    ErrorIntegracion,
    Llamada,
    Reintentos,
    Secretos,
    TipoError,
    error_de_respuesta,
    limpiar,
)

RENOVAR_TOKEN_S = 23 * 3600
DIAS_SUELO = 7
DIAS_PLANTA = 30
DIAS_NDVI = 10

EP_TOKEN = "auth/api-token"
EP_SUELO = "api/v1/SoilHourlyData"
EP_PLANTA = "api/v1/ProjectsDailyData"
EP_PRONOSTICO = "api/v1/ProjectsClimateForecastData"
EP_NDVI = "api/v1/NdviImages"


def tramos(desde: dt.date, hasta: dt.date, dias: int) -> list[tuple[dt.date, dt.date]]:
    """Tramos de como mucho ``dias`` días (ambos extremos incluidos)."""
    salida = []
    actual = desde
    while actual <= hasta:
        fin = min(actual + dt.timedelta(days=dias - 1), hasta)
        salida.append((actual, fin))
        actual = fin + dt.timedelta(days=1)
    return salida


def leer_zip_ndvi(contenido: bytes) -> dict[str, Any]:
    """ZIP de ``NdviImages`` -> ``{"manifest": {...}, "histogramas": [...]}`` (los PNG no se
    guardan: el modelo usa los histogramas)."""
    try:
        with zipfile.ZipFile(io.BytesIO(contenido)) as archivo:
            nombres = archivo.namelist()
            manifest = json.loads(archivo.read("manifest.json")) if "manifest.json" in nombres else None
            histogramas = [json.loads(archivo.read(n).decode("utf-8"))
                           for n in sorted(nombres) if n.endswith("_histogram.json")]
    except (zipfile.BadZipFile, KeyError, ValueError) as error:
        raise ErrorIntegracion(TipoError.RESPUESTA, f"ZIP de NDVI inválido ({type(error).__name__})",
                               status_code=200, endpoint=f"/{EP_NDVI}") from None
    return {"manifest": manifest, "histogramas": histogramas}


class ClientePhytech:
    def __init__(
        self, *, api_key: str, api_secret: str, base_url: str,
        transport: httpx.BaseTransport | None = None, reintentos: Reintentos | None = None,
        reloj: Callable[[], float] = time.monotonic,
    ) -> None:
        if not api_key or not api_secret:
            raise ErrorIntegracion(TipoError.CONFIGURACION, "Faltan PHYTECH_API_KEY / PHYTECH_API_SECRET")
        self._api_key = api_key
        self._api_secret = api_secret
        self._secretos = Secretos()
        self._secretos.agregar(api_key, api_secret)
        self.base_url = base_url.rstrip("/")
        self.reintentos = reintentos or Reintentos()
        self._reloj = reloj
        self._token: str | None = None
        self._token_desde: float | None = None
        self.renovaciones = 0  # cuántas veces se pidió token (diagnóstico y pruebas)
        self._http = httpx.Client(timeout=TIMEOUT, transport=transport, follow_redirects=False)

    def cerrar(self) -> None:
        self._token = None
        self._http.close()

    def __enter__(self) -> ClientePhytech:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.cerrar()

    # --- Token ------------------------------------------------------------------

    def _autenticar(self) -> None:
        self._token = None
        respuesta = self.reintentos.pedir(
            self._http, "POST", f"{self.base_url}/{EP_TOKEN}",
            headers={"X-API-KEY": self._api_key, "X-API-SECRET-KEY": self._api_secret},
            secretos=self._secretos,
        )
        if respuesta.status_code in (400, 401, 403):
            raise ErrorIntegracion(
                TipoError.CREDENCIALES,
                f"Phytech rechazó las credenciales (HTTP {respuesta.status_code}): revisa "
                "PHYTECH_API_KEY / PHYTECH_API_SECRET",
                status_code=respuesta.status_code, endpoint=f"/{EP_TOKEN}",
            )
        if respuesta.status_code != 200:
            raise error_de_respuesta(respuesta, self._secretos)
        try:
            token = respuesta.json()["data"]["token"]
        except (ValueError, KeyError, TypeError):
            raise ErrorIntegracion(TipoError.RESPUESTA, "Respuesta de token inesperada",
                                   status_code=200, endpoint=f"/{EP_TOKEN}") from None
        if not isinstance(token, str) or not token:
            raise ErrorIntegracion(TipoError.RESPUESTA, "Respuesta de token vacía",
                                   status_code=200, endpoint=f"/{EP_TOKEN}")
        self._token = token
        self._token_desde = self._reloj()
        self._secretos.agregar(token)
        self.renovaciones += 1

    def _asegurar_token(self) -> str:
        vencido = self._token_desde is None or self._reloj() - self._token_desde >= RENOVAR_TOKEN_S
        if self._token is None or vencido:
            self._autenticar()
        assert self._token is not None
        return self._token

    # --- Llamadas ---------------------------------------------------------------

    def _get(self, ruta: str, params: dict[str, Any], *, binario: bool = False) -> Any:
        url = f"{self.base_url}/{ruta}"
        for renovado in (False, True):
            token = self._asegurar_token()
            respuesta = self.reintentos.get(
                self._http, url, params=params, headers={"Authorization": f"Bearer {token}"},
                secretos=self._secretos, no_reintentar=(401,),
            )
            if respuesta.status_code == 401:
                if renovado:
                    raise ErrorIntegracion(
                        TipoError.CREDENCIALES,
                        "Phytech respondió 401 también con un token nuevo: revisa PHYTECH_API_KEY / "
                        "PHYTECH_API_SECRET o los permisos de la cuenta",
                        status_code=401, endpoint=f"/{ruta}",
                    )
                self._autenticar()  # el token venció o lo revocaron antes de tiempo
                continue
            break
        if respuesta.status_code != 200:
            raise error_de_respuesta(respuesta, self._secretos)
        if binario and respuesta.content[:2] == b"PK":
            return respuesta.content
        try:
            cuerpo = respuesta.json()
        except ValueError:
            raise ErrorIntegracion(TipoError.RESPUESTA, "La respuesta no es JSON ni ZIP",
                                   status_code=200, endpoint=f"/{ruta}") from None
        if not isinstance(cuerpo, dict) or cuerpo.get("statusCode") != 200:
            estado = cuerpo.get("statusCode") if isinstance(cuerpo, dict) else None
            detalle = cuerpo.get("error") if isinstance(cuerpo, dict) else None
            raise ErrorIntegracion(
                TipoError.RESPUESTA,
                limpiar(f"statusCode {estado}: {detalle}", self._secretos),
                status_code=estado if isinstance(estado, int) else 200, endpoint=f"/{ruta}",
            )
        if binario:
            raise ErrorIntegracion(TipoError.RESPUESTA, "Se esperaba un ZIP", status_code=200,
                                   endpoint=f"/{ruta}")
        return cuerpo.get("data")

    def _rango(self, ruta: str, area_id: int, desde: dt.date, hasta: dt.date, maximo: int,
               *, binario: bool = False) -> tuple[dict[str, Any], Any]:
        dias = (hasta - desde).days + 1
        if dias < 1 or dias > maximo:
            raise ValueError(f"{ruta}: el rango debe tener entre 1 y {maximo} días (pedidos {dias})")
        params = {"area_id": area_id, "start_date": desde.isoformat(), "end_date": hasta.isoformat()}
        return params, self._get(ruta, params, binario=binario)

    def suelo_horario(self, area_id: int, desde: dt.date, hasta: dt.date) -> Llamada:
        params, data = self._rango(EP_SUELO, area_id, desde, hasta, DIAS_SUELO)
        return Llamada(EP_SUELO, params, data)

    def planta_diaria(self, area_id: int, desde: dt.date, hasta: dt.date) -> Llamada:
        params, data = self._rango(EP_PLANTA, area_id, desde, hasta, DIAS_PLANTA)
        return Llamada(EP_PLANTA, params, data)

    def ndvi(self, area_id: int, desde: dt.date, hasta: dt.date) -> Llamada:
        params, contenido = self._rango(EP_NDVI, area_id, desde, hasta, DIAS_NDVI, binario=True)
        return Llamada(EP_NDVI, params, leer_zip_ndvi(contenido))

    def pronostico(self, area_id: int) -> Llamada:
        params = {"area_id": area_id}
        return Llamada(EP_PRONOSTICO, params, self._get(EP_PRONOSTICO, params))
