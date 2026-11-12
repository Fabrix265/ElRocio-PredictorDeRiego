"""Descarga el modelo .joblib durante el build de Render (el modelo no está en git, H10).

Lee del entorno:
- MODELO_URL: enlace de descarga (por ejemplo, una URL firmada de un bucket privado). Es un
  secreto: nunca se imprime.
- ML_MODEL_PATH: dónde guardarlo, relativo a la raíz del repo.
- ML_MODEL_SHA256: sha256 esperado. Si no coincide, el build falla (el backend también lo
  verifica al cargarlo).

Uso: python deploy/render/descargar_modelo.py  (desde la raíz del repo)
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
RUTA_POR_DEFECTO = "ml/models/plan_riego/actual/modelo_plan_riego.joblib"


def fallar(mensaje: str) -> None:
    print(f"[modelo] ERROR: {mensaje}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    url = os.environ.get("MODELO_URL", "").strip()
    esperado = os.environ.get("ML_MODEL_SHA256", "").strip().lower()
    ruta = Path(os.environ.get("ML_MODEL_PATH", "").strip() or RUTA_POR_DEFECTO)
    destino = ruta if ruta.is_absolute() else RAIZ / ruta

    if not url:
        fallar("falta la variable MODELO_URL")
    if not esperado:
        fallar("falta la variable ML_MODEL_SHA256")

    destino.parent.mkdir(parents=True, exist_ok=True)
    sha = hashlib.sha256()
    total = 0
    peticion = urllib.request.Request(url, headers={"User-Agent": "riego-build"})
    try:
        with urllib.request.urlopen(peticion, timeout=120) as respuesta, tempfile.NamedTemporaryFile(
            dir=destino.parent, delete=False
        ) as tmp:
            while bloque := respuesta.read(1 << 20):
                sha.update(bloque)
                tmp.write(bloque)
                total += len(bloque)
    except Exception as exc:  # noqa: BLE001 - se informa sin mostrar la URL
        fallar(f"no se pudo descargar el modelo ({type(exc).__name__})")

    obtenido = sha.hexdigest()
    if obtenido != esperado:
        Path(tmp.name).unlink(missing_ok=True)
        fallar(f"el sha256 no coincide (obtenido {obtenido}); revisa MODELO_URL y ML_MODEL_SHA256")

    os.replace(tmp.name, destino)
    print(f"[modelo] OK: {total / 2**20:.1f} MB, sha256 verificado, guardado en {ruta}")


if __name__ == "__main__":
    main()
