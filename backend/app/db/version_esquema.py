"""¿La base de datos tiene todas las migraciones que espera el código?

Si se actualiza el código sin aplicar las migraciones nuevas (``alembic upgrade head``), las
consultas fallan con errores de columna inexistente que no dicen qué hacer. Esta comprobación
lo detecta al arrancar (log) y en ``/health``. ``riego_app`` puede leer ``riego.alembic_version``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from app.core.config import BACKEND_ROOT

EstadoMigraciones = Literal["al_dia", "pendientes", "desconocido"]


@lru_cache
def revision_esperada() -> str | None:
    """Última migración del código (head de ``backend/alembic``)."""
    registro = logging.getLogger("alembic")
    nivel = registro.level
    registro.setLevel(logging.WARNING)  # sin el ruido «setup plugin ...» en cada arranque
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        config = Config(str(BACKEND_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        return ScriptDirectory.from_config(config).get_current_head()
    finally:
        registro.setLevel(nivel)


@dataclass(frozen=True)
class VersionEsquema:
    estado: EstadoMigraciones
    bd: str | None
    esperada: str | None

    @property
    def mensaje(self) -> str:
        return (
            f"La base de datos está en la migración {self.bd or 'ninguna'} y el código necesita la "
            f"{self.esperada}: aplica las migraciones pendientes (desde backend/: "
            f"python -m alembic upgrade head) antes de usar el sistema."
        )


def comprobar(conexion: Connection | Session) -> VersionEsquema:
    """Compara la revisión de la BD con la del código; no lanza excepciones."""
    try:
        esperada = revision_esperada()
    except Exception:  # noqa: BLE001 - sin scripts de alembic no se puede comparar
        return VersionEsquema("desconocido", None, None)
    try:
        bd = conexion.execute(text("SELECT version_num FROM riego.alembic_version")).scalar()
    except Exception:  # noqa: BLE001 - tabla ausente o sin permiso
        conexion.rollback()
        return VersionEsquema("desconocido", None, esperada)
    return VersionEsquema("al_dia" if bd == esperada else "pendientes", bd, esperada)
