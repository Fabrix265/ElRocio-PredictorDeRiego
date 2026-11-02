from __future__ import annotations

import hashlib
import os
import platform
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np


def set_seeds(seed: int = 42) -> None:
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def environment_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
    }
    try:
        import pandas as pd

        info["pandas"] = pd.__version__
    except Exception:
        pass
    try:
        import sklearn

        info["scikit_learn"] = sklearn.__version__
    except Exception:
        pass
    try:
        import xgboost

        info["xgboost"] = xgboost.__version__
    except Exception:
        pass
    try:
        import matplotlib

        info["matplotlib"] = matplotlib.__version__
    except Exception:
        pass
    return info
