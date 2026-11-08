"""Piezas comunes de los clientes HTTP de las APIs externas (WeatherLink y Phytech).

- :class:`ErrorIntegracion`: error con ``{tipo, status_code, endpoint, mensaje}`` listo para
  guardar en ``ingesta_corrida.errores``. El ``endpoint`` es solo la ruta (sin query: la query de
  WeatherLink lleva la ``api-key``) y el mensaje pasa por :func:`limpiar`, que quita los valores
  de las claves y lo que :func:`app.core.logging.redactar` reconoce como secreto.
- :class:`Reintentos`: GET con reintentos y espera creciente ante 429, 5xx y errores de red
  (``Retry-After`` si la API lo manda, con tope). El 401 lo maneja cada cliente.

Los clientes nunca registran URLs completas ni cabeceras. httpx registra en INFO la URL completa
(con la ``api-key`` de WeatherLink en la query): al importar este módulo sus loggers quedan en
WARNING y con el filtro de redacción propio, aunque no se haya llamado a ``configurar_logging``
(pruebas, scripts).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.logging import REDACTADO, FiltroRedaccion, redactar

logger = logging.getLogger(__name__)


def _silenciar_httpx() -> None:
    for nombre in ("httpx", "httpcore"):
        registro = logging.getLogger(nombre)
        registro.setLevel(logging.WARNING)
        if not any(isinstance(f, FiltroRedaccion) for f in registro.filters):
            registro.addFilter(FiltroRedaccion())


_silenciar_httpx()

TIMEOUT = httpx.Timeout(60.0, connect=15.0)
MAX_INTENTOS = 4
ESPERA_MAXIMA_S = 60.0
LARGO_MENSAJE = 300


class TipoError:
    RED = "red"                      # sin respuesta (timeout, DNS, conexión)
    HTTP = "http"                    # respuesta con estado de error que no se reintenta
    REINTENTOS = "reintentos_agotados"  # 429/5xx/red repetidos
    CREDENCIALES = "credenciales"    # 401/403 tras renovar, o claves sin configurar
    RESPUESTA = "respuesta"          # cuerpo inesperado (no JSON, statusCode != 200, ZIP inválido)
    CONFIGURACION = "configuracion"
    INTERNO = "interno"


class ErrorIntegracion(Exception):
    """Error de una llamada a una API externa (sin secretos)."""

    def __init__(self, tipo: str, mensaje: str, *, status_code: int | None = None,
                 endpoint: str | None = None) -> None:
        super().__init__(mensaje)
        self.tipo = tipo
        self.mensaje = mensaje
        self.status_code = status_code
        self.endpoint = endpoint

    def como_dict(self) -> dict[str, Any]:
        return {"tipo": self.tipo, "status_code": self.status_code, "endpoint": self.endpoint,
                "mensaje": self.mensaje}


@dataclass
class Secretos:
    """Valores que nunca deben salir en un mensaje (se reemplazan por ``[REDACTADO]``)."""

    valores: list[str] = field(default_factory=list)

    def agregar(self, *valores: str | None) -> None:
        for valor in valores:
            if valor and len(valor) >= 4 and valor not in self.valores:
                self.valores.append(valor)

    def limpiar(self, texto: str) -> str:
        for valor in self.valores:
            texto = texto.replace(valor, REDACTADO)
        return redactar(texto)


def limpiar(texto: str, secretos: Secretos | None = None) -> str:
    texto = secretos.limpiar(texto) if secretos else redactar(texto)
    return texto[:LARGO_MENSAJE]


def ruta_sin_query(url: httpx.URL | str) -> str:
    """Solo la ruta de la URL (``/v2/historic/28494``), nunca la query."""
    return httpx.URL(str(url)).path


def _espera_retry_after(respuesta: httpx.Response) -> float | None:
    valor = respuesta.headers.get("retry-after")
    if valor is None:
        return None
    try:
        return max(0.0, float(valor))
    except ValueError:
        return None


@dataclass
class Reintentos:
    """Política de reintentos. ``dormir`` se reemplaza en las pruebas."""

    max_intentos: int = MAX_INTENTOS
    espera_429_s: float = 10.0
    espera_5xx_s: float = 5.0
    espera_red_s: float = 2.0
    dormir: Callable[[float], None] = time.sleep

    def esperar(self, segundos: float) -> None:
        self.dormir(min(segundos, ESPERA_MAXIMA_S))

    def get(self, cliente: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
        return self.pedir(cliente, "GET", url, **kwargs)

    def pedir(
        self, cliente: httpx.Client, metodo: str, url: str, *, params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None, secretos: Secretos | None = None,
        no_reintentar: Iterable[int] = (),
    ) -> httpx.Response:
        """Petición con reintentos. Devuelve la respuesta final (2xx, 4xx o un estado de
        ``no_reintentar``); lanza :class:`ErrorIntegracion` si se agotan los intentos."""
        endpoint = ruta_sin_query(url)
        ultimo: ErrorIntegracion | None = None
        for intento in range(1, self.max_intentos + 1):
            try:
                respuesta = cliente.request(metodo, url, params=params, headers=headers)
            except httpx.HTTPError as error:
                ultimo = ErrorIntegracion(
                    TipoError.RED, limpiar(f"{type(error).__name__}: {error}", secretos), endpoint=endpoint
                )
                logger.warning("Error de red en %s (intento %s/%s): %s", endpoint, intento,
                               self.max_intentos, type(error).__name__)
                if intento < self.max_intentos:
                    self.esperar(self.espera_red_s * intento)
                continue
            codigo = respuesta.status_code
            if codigo in set(no_reintentar):
                return respuesta
            if codigo == 429 or codigo >= 500:
                base = self.espera_429_s if codigo == 429 else self.espera_5xx_s
                ultimo = ErrorIntegracion(
                    TipoError.HTTP, f"HTTP {codigo}", status_code=codigo, endpoint=endpoint
                )
                logger.warning("HTTP %s en %s (intento %s/%s)", codigo, endpoint, intento, self.max_intentos)
                if intento < self.max_intentos:
                    self.esperar(_espera_retry_after(respuesta) or base * intento)
                continue
            return respuesta
        assert ultimo is not None
        raise ErrorIntegracion(
            TipoError.REINTENTOS,
            f"Sin respuesta válida tras {self.max_intentos} intentos ({ultimo.mensaje})",
            status_code=ultimo.status_code, endpoint=endpoint,
        )


def error_de_respuesta(respuesta: httpx.Response, secretos: Secretos | None = None) -> ErrorIntegracion:
    """Error para una respuesta 4xx que no se reintenta (cuerpo acotado y redactado)."""
    codigo = respuesta.status_code
    tipo = TipoError.CREDENCIALES if codigo in (401, 403) else TipoError.HTTP
    detalle = respuesta.text[:200].strip().replace("\n", " ")
    mensaje = f"HTTP {codigo}" + (f": {detalle}" if detalle else "")
    return ErrorIntegracion(tipo, limpiar(mensaje, secretos), status_code=codigo,
                            endpoint=ruta_sin_query(respuesta.request.url))


@dataclass
class Llamada:
    """Una llamada a la API: lo que se guarda en ``ingesta_crudo`` (parámetros de negocio, sin
    claves) y el payload tal cual llegó (JSON)."""

    endpoint: str
    parametros: dict[str, Any]
    payload: Any
