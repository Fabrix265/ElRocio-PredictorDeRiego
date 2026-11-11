"""``python -m app.jobs``: proceso de tareas programadas (desde ``backend/``).

``python -m app.jobs --una-vez`` procesa la cola de correos una sola vez y termina.
"""

from __future__ import annotations

import argparse
import logging

from app.core.logging import configurar_logging
from app.jobs import tareas
from app.jobs.runner import crear_programador

logger = logging.getLogger("app.jobs")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.jobs", description="Tareas programadas del backend de riego.")
    parser.add_argument("--una-vez", action="store_true", help="Procesa la cola de correos una vez y termina.")
    args = parser.parse_args(argv)

    configurar_logging()
    if args.una_vez:
        resultado = tareas.enviar_correos()
        print(
            f"Correos: {resultado.enviados} enviado(s), {resultado.sin_destinatarios} sin destinatarios, "
            f"{resultado.reintentos} a reintentar, {resultado.errores} con error."
        )
        return 0

    programador = crear_programador(en_segundo_plano=False)
    logger.info("Tareas programadas iniciadas (Ctrl+C para detener)")
    try:
        programador.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Tareas programadas detenidas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
