from __future__ import annotations

import pandas as pd

from riego_ml.config.schema import SourceConfig
from riego_ml.data.source import build_source


def apply_column_map(
    df: pd.DataFrame, column_map: dict[str, str] | None
) -> pd.DataFrame:
    if not column_map:
        return df
    rename = {
        source_name: canonical_name
        for canonical_name, source_name in column_map.items()
        if source_name in df.columns
    }
    return df.rename(columns=rename)


def load_dataset(config: SourceConfig) -> pd.DataFrame:
    source = build_source(config)
    df = source.load()
    if df.empty:
        raise ValueError(f"El archivo de datos está vacío: {config.path}")
    return apply_column_map(df, config.column_map)
