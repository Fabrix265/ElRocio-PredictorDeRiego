from __future__ import annotations

import os
import platform
import random
import sys
from typing import Any

import numpy as np


def set_seeds(seed: int = 42) -> None:
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


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
    return info
