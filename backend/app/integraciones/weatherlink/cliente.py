"""Cliente de WeatherLink v2 (``/historic/{station_id}``), solo lectura.

- Autenticación: ``api-key`` en la query y cabecera ``X-Api-Secret`` (H7). Ninguna de las dos se
  registra ni se guarda: :class:`~app.integraciones.http.Llamada` lleva solo los parámetros de
  negocio y los errores llevan la ruta sin query.
- Máximo 24 h por llamada: **una llamada por día local de Lima**. La API devuelve los registros
  con ``ts`` (fin del intervalo) en ``(start-timestamp, end-timestamp]``; se pide
  ``(00:00 − 1 s, 24:00 − 1 s]`` del día, así llegan exactamente los registros de 00:00 a 23:30,
  que son los que pertenecen a ese día (el de las 00:00 es del día nuevo, como en el Excel).
- Reintentos con espera ante 429, 5xx y errores de red; 401/403 = credenciales inválidas.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx

from app.core.tiempo import zona_lima
from app.integraciones.http import (
    TIMEOUT,
    ErrorIntegracion,
    Llamada,
    Reintentos,
    Secretos,
    TipoError,
    error_de_respuesta,
)


def rango_dia(dia: dt.date) -> tuple[int, int]:
    """``(start-timestamp, end-timestamp)`` de un día local de Lima: 24 h exactas."""
    inicio = dt.datetime.combine(dia, dt.time(), tzinfo=zona_lima())
    fin = dt.datetime.combine(dia + dt.timedelta(days=1), dt.time(), tzinfo=zona_lima())
    return int(inicio.timestamp()) - 1, int(fin.timestamp()) - 1


class ClienteWeatherLink:
    def __init__(
        self, *, api_key: str, api_secret: str, base_url: str, station_id: int,
        transport: httpx.BaseTransport | None = None, reintentos: Reintentos | None = None,
    ) -> None:
        if not api_key or not api_secret:
            raise ErrorIntegracion(TipoError.CONFIGURACION,
                                   "Faltan WEATHERLINK_API_KEY / WEATHERLINK_API_SECRET")
        self._api_key = api_key
        self._secretos = Secretos()
        self._secretos.agregar(api_key, api_secret)
        self.station_id = station_id
        self.base_url = base_url.rstrip("/")
        self.reintentos = reintentos or Reintentos()
        self._http = httpx.Client(
            timeout=TIMEOUT, transport=transport, headers={"X-Api-Secret": api_secret},
            follow_redirects=False,
        )

    def cerrar(self) -> None:
        self._http.close()

    def __enter__(self) -> ClienteWeatherLink:
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.cerrar()

    def historico_dia(self, dia: dt.date) -> Llamada:
        """Registros de 30 min de ``dia`` (hora de Lima) tal cual los entrega la API."""
        inicio, fin = rango_dia(dia)
        ruta = f"historic/{self.station_id}"
        respuesta = self.reintentos.get(
            self._http, f"{self.base_url}/{ruta}",
            params={"api-key": self._api_key, "start-timestamp": inicio, "end-timestamp": fin},
            secretos=self._secretos,
        )
        if respuesta.status_code != 200:
            raise error_de_respuesta(respuesta, self._secretos)
        try:
            payload = respuesta.json()
        except ValueError:
            raise ErrorIntegracion(TipoError.RESPUESTA, "La respuesta no es JSON",
                                   status_code=200, endpoint=f"/{ruta}") from None
        if not isinstance(payload, dict):
            raise ErrorIntegracion(TipoError.RESPUESTA, "Respuesta inesperada (se esperaba un objeto)",
                                   status_code=200, endpoint=f"/{ruta}")
        parametros = {"station_id": self.station_id, "dia": dia.isoformat(),
                      "start-timestamp": inicio, "end-timestamp": fin}
        return Llamada(endpoint=ruta, parametros=parametros, payload=payload)
