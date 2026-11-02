from __future__ import annotations

from datetime import datetime
from pathlib import Path


def ensure_dir(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def run_id(name: str = "riego") -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{name}_{stamp}"


def relative_to(path: str | Path, base: str | Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path(base).resolve()))
    except ValueError:
        return str(path)
