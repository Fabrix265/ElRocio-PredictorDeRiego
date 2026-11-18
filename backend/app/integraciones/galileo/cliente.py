"""Cliente de solo lectura del Data Warehouse de Fabric (SQL endpoint, TDS 1433, Entra ID).

- Driver: ``mssql-python`` (oficial de Microsoft, trae su propio ODBC).
- Autenticación:
  - ``usuario``: ``Authentication=ActiveDirectoryPassword`` del propio driver (usuario y contraseña
    de Entra ID; no sirve si la cuenta exige MFA). Un token pedido aparte con la app de Azure CLI
    se autentica pero Fabric le niega el acceso a la base (probado el 2026-11-17).
  - ``servicio``: service principal (client id + secreto); el token se pide con MSAL y se entrega
    al driver con ``token_provider``.
- La contraseña o el secreto nunca se registran; los mensajes de error se limpian con
  :func:`sin_secretos`.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from app.integraciones.galileo.config import ConfiguracionFabric

ALCANCE_SQL = "https://database.windows.net/.default"


class ErrorFabric(RuntimeError):
    """Fallo al conectar o consultar Fabric (mensaje ya sin secretos)."""


@dataclass(frozen=True)
class _Token:
    token: str
    expires_on: int


class ProveedorToken:
    """``get_token(scope)`` para ``mssql_python.connect(token_provider=...)`` (modo ``servicio``)."""

    def __init__(self, cfg: ConfiguracionFabric):
        self.cfg = cfg

    def get_token(self, *_scopes: str, **_kwargs: Any) -> _Token:
        import msal

        cfg = self.cfg
        autoridad = f"https://login.microsoftonline.com/{cfg.inquilino_efectivo}"
        app = msal.ConfidentialClientApplication(
            cfg.usuario, client_credential=cfg.clave.get_secret_value(), authority=autoridad)
        r = app.acquire_token_for_client(scopes=[ALCANCE_SQL])
        if "access_token" not in r:
            codigos = ",".join(str(c) for c in r.get("error_codes") or [])
            detalle = (r.get("error_description") or "").splitlines()[0][:240]
            raise ErrorFabric(sin_secretos(
                f"Entra ID rechazó el inicio de sesión: {r.get('error')} [{codigos}] {detalle}", cfg))
        return _Token(r["access_token"], int(time.time()) + int(r.get("expires_in", 3600)))


def _escapar(valor: str) -> str:
    # Valor ODBC entre llaves: una "}" se escribe "}}".
    return "{" + valor.replace("}", "}}") + "}"


def cadena_conexion(cfg: ConfiguracionFabric) -> str:
    partes = [
        f"Server={cfg.servidor},1433",
        f"Database={_escapar(cfg.base_datos)}",
        "Encrypt=yes",
        "TrustServerCertificate=no",
        "ApplicationIntent=ReadOnly",
    ]
    if cfg.autenticacion == "usuario":
        partes += ["Authentication=ActiveDirectoryPassword", f"UID={_escapar(cfg.usuario)}",
                   f"PWD={_escapar(cfg.clave.get_secret_value())}"]
    return ";".join(partes)


def sin_secretos(texto: str, cfg: ConfiguracionFabric) -> str:
    clave = cfg.clave.get_secret_value()
    if clave:
        texto = texto.replace(clave, "***")
    return texto


@contextmanager
def conexion(cfg: ConfiguracionFabric) -> Iterator[Any]:
    """Conexión de solo lectura (no se hace commit de nada)."""
    import mssql_python

    if not cfg.configurada:
        raise ErrorFabric("Falta configurar " + ", ".join(cfg.faltantes()) + " (backend/.env.fabric)")
    extra: dict[str, Any] = {}
    if cfg.autenticacion == "servicio":
        proveedor = ProveedorToken(cfg)
        proveedor.get_token(ALCANCE_SQL)  # falla rápido y con el código de Entra ID
        extra["token_provider"] = proveedor
    try:
        con = mssql_python.connect(cadena_conexion(cfg), autocommit=True, timeout=cfg.timeout_s, **extra)
    except ErrorFabric:
        raise
    except Exception as error:  # noqa: BLE001 - se re-lanza limpio
        raise ErrorFabric(sin_secretos(f"{type(error).__name__}: {error}", cfg)) from None
    try:
        yield con
    finally:
        con.close()


ENDPOINT = "fabric:silver_galileo_consolas"


class ClienteGalileo:
    """Lee las filas del controlador por rango de fechas (una conexión para toda la ingesta)."""

    def __init__(self, cfg: ConfiguracionFabric | None = None):
        from app.integraciones.http import ErrorIntegracion, TipoError

        self.cfg = cfg or ConfiguracionFabric()
        if not self.cfg.configurada:
            raise ErrorIntegracion(TipoError.CONFIGURACION,
                                   "Falta configurar " + ", ".join(self.cfg.faltantes()), endpoint=ENDPOINT)
        self._contexto = conexion(self.cfg)
        try:
            self._con = self._contexto.__enter__()
        except ErrorFabric as error:
            tipo = TipoError.CREDENCIALES if "authentication" in str(error).lower() or "Entra ID" in str(
                error) else TipoError.RED
            raise ErrorIntegracion(tipo, str(error)[:300], endpoint=ENDPOINT) from None
        self._columnas: dict[str, str] | None = None
        self._tiene_consola = False

    def columnas(self) -> dict[str, str]:
        """Canónico -> nombre real (``adaptador.resolver_columnas``)."""
        from app.integraciones.galileo.adaptador import resolver_columnas

        if self._columnas is None:
            _, filas = consultar(self._con, (
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?"),
                (self.cfg.esquema, self.cfg.tabla))
            nombres = [f[0] for f in filas]
            self._tiene_consola = any(n.lower() == "consola" for n in nombres)
            self._columnas = resolver_columnas(nombres)
        return self._columnas

    def filas(self, desde: dt.date, hasta: dt.date) -> list[dict[str, Any]]:
        """Filas con ``desde <= fecha <= hasta`` (todas las columnas, nombres reales)."""
        from app.integraciones.http import ErrorIntegracion, TipoError

        try:
            fecha = self.columnas()["fecha"].replace("]", "]]")
            sql = f"SELECT * FROM {self.cfg.tabla_calificada()} WHERE [{fecha}] >= ? AND [{fecha}] < ?"
            parametros: tuple = (desde, hasta + dt.timedelta(days=1))
            if self.cfg.consola and self._tiene_consola:
                sql += " AND [consola] = ?"
                parametros += (self.cfg.consola,)
            cols, filas = consultar(self._con, sql, parametros)
        except ValueError as error:
            raise ErrorIntegracion(TipoError.RESPUESTA, str(error), endpoint=ENDPOINT) from None
        except Exception as error:  # noqa: BLE001
            raise ErrorIntegracion(TipoError.RED, sin_secretos(f"{type(error).__name__}: {error}", self.cfg)[:300],
                                   endpoint=ENDPOINT) from None
        return [dict(zip(cols, f, strict=True)) for f in filas]

    def cerrar(self) -> None:
        self._contexto.__exit__(None, None, None)


def consultar(con: Any, sql: str, parametros: tuple = ()) -> tuple[list[str], list[tuple]]:
    """``(columnas, filas)`` de una consulta."""
    cur = con.cursor()
    try:
        if parametros:
            cur.execute(sql, parametros)
        else:
            cur.execute(sql)
        columnas = [d[0] for d in cur.description or []]
        return columnas, [tuple(f) for f in cur.fetchall()]
    finally:
        cur.close()
