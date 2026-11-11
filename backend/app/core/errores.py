"""Errores de la aplicación con mensaje en español (respuesta ``{"detail": "..."}``).

Los servicios lanzan estas excepciones sin depender de FastAPI; ``app.main`` las traduce a
respuestas HTTP.
"""

from __future__ import annotations


class ErrorApp(Exception):
    status_code = 400
    detail = "Solicitud no válida"

    def __init__(self, detail: str | None = None, *, headers: dict[str, str] | None = None):
        self.detail = detail or type(self).detail
        self.headers = headers
        super().__init__(self.detail)


class SolicitudInvalida(ErrorApp):
    status_code = 400


class NoAutenticado(ErrorApp):
    status_code = 401
    detail = "Sesión no válida o vencida"

    def __init__(self, detail: str | None = None):
        super().__init__(detail, headers={"WWW-Authenticate": "Bearer"})


class CredencialesInvalidas(NoAutenticado):
    detail = "Usuario o contraseña incorrectos"


class SinPermiso(ErrorApp):
    status_code = 403
    detail = "No tienes permiso para realizar esta acción"


class NoEncontrado(ErrorApp):
    status_code = 404
    detail = "Recurso no encontrado"


class Conflicto(ErrorApp):
    status_code = 409
    detail = "El recurso ya existe"


class DatosInvalidos(ErrorApp):
    """Reglas de negocio sobre los datos (p. ej. política de contraseña)."""

    status_code = 422


class LimiteExcedido(ErrorApp):
    status_code = 429

    def __init__(self, segundos: float):
        segundos = max(1, int(-(-segundos // 1)))
        minutos = max(1, -(-segundos // 60))
        unidad = "minuto" if minutos == 1 else "minutos"
        super().__init__(
            f"Demasiados intentos. Vuelve a intentarlo en {minutos} {unidad}.",
            headers={"Retry-After": str(segundos)},
        )
        self.segundos = segundos
