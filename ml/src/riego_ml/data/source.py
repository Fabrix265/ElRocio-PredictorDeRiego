from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

from riego_ml.config.schema import SourceConfig


class DataSource(ABC):
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @abstractmethod
    def load(self) -> pd.DataFrame:
        raise NotImplementedError


class ExcelSource(DataSource):
    def __init__(self, path: str | Path, sheet: str | None = None):
        super().__init__(path)
        self.sheet = sheet

    def load(self) -> pd.DataFrame:
        return pd.read_excel(self.path, sheet_name=self.sheet)


class CsvSource(DataSource):
    def __init__(self, path: str | Path, sep: str = ",", encoding: str = "utf-8"):
        super().__init__(path)
        self.sep = sep
        self.encoding = encoding

    def load(self) -> pd.DataFrame:
        return pd.read_csv(self.path, sep=self.sep, encoding=self.encoding)


class ParquetSource(DataSource):
    def load(self) -> pd.DataFrame:
        return pd.read_parquet(self.path)


def build_source(config: SourceConfig) -> DataSource:
    if config.path is None:
        raise ValueError("La fuente de datos no tiene path.")
    if config.type == "excel":
        return ExcelSource(config.path, config.sheet)
    if config.type == "csv":
        return CsvSource(config.path, config.sep, config.encoding)
    if config.type == "parquet":
        return ParquetSource(config.path)
    raise ValueError(f"Tipo de fuente no soportado: {config.type}")
