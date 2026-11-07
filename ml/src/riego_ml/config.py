"""Configuración del pipeline (``ml/config/pipeline.yaml``).

Las rutas relativas del YAML se resuelven contra la raíz del repositorio, de
modo que los comandos funcionan igual desde cualquier carpeta.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from riego_ml.settings import DEFAULT_CONFIG, PROJECT_ROOT


class ConfigError(ValueError):
    """Configuración inválida."""


@dataclass
class Rutas:
    riego: Path
    meteo: Path
    phytech: Path
    interim_dir: Path
    processed_dir: Path
    modelos_dir: Path
    reportes_dir: Path


@dataclass
class Fuentes:
    hoja_riego: str = "MOD5"
    phytech_project_id: int = 907557


@dataclass
class Preparacion:
    desde: str | None = None
    hasta: str | None = None
    min_duracion_min: float = 5.0
    min_riego_m3ha: float = 2.0
    incluir_meteo_dia: bool = False


@dataclass
class Split:
    test: float = 0.2
    validacion: float = 0.15
    gap_dias: int = 7


@dataclass
class Plan:
    max_ciclos: int = 5
    pausa_min_entre_ciclos: float = 0.0


@dataclass
class Tuning:
    habilitado: bool = False
    n_iter: int = 15
    folds: int = 3
    n_jobs: int = -1


@dataclass
class ModeloConfig:
    habilitado: bool = True
    clasificacion: dict[str, Any] = field(default_factory=dict)
    regresion: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    rutas: Rutas
    fuentes: Fuentes = field(default_factory=Fuentes)
    preparacion: Preparacion = field(default_factory=Preparacion)
    split: Split = field(default_factory=Split)
    plan: Plan = field(default_factory=Plan)
    tuning: Tuning = field(default_factory=Tuning)
    modelos: dict[str, ModeloConfig] = field(default_factory=dict)
    seed: int = 42
    excluir_dias_incompletos_eval: bool = True
    path: Path | None = None

    def modelos_habilitados(self) -> list[str]:
        return [nombre for nombre, cfg in self.modelos.items() if cfg.habilitado]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _resolver(valor: str | Path) -> Path:
    path = Path(valor)
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _seccion(cls, datos: dict | None, nombre: str):
    datos = datos or {}
    try:
        return cls(**datos)
    except TypeError as exc:
        raise ConfigError(f"Sección '{nombre}' inválida: {exc}") from exc


def load_config(path: str | Path | None = None) -> Config:
    config_path = _resolver(path) if path else DEFAULT_CONFIG
    if not config_path.exists():
        raise ConfigError(f"No existe el archivo de configuración: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    rutas_raw = raw.get("rutas") or {}
    try:
        rutas = Rutas(**{k: _resolver(v) for k, v in rutas_raw.items()})
    except TypeError as exc:
        raise ConfigError(f"Sección 'rutas' inválida: {exc}") from exc

    modelos = {
        nombre: _seccion(ModeloConfig, datos, f"modelos.{nombre}")
        for nombre, datos in (raw.get("modelos") or {}).items()
    }
    config = Config(
        rutas=rutas,
        fuentes=_seccion(Fuentes, raw.get("fuentes"), "fuentes"),
        preparacion=_seccion(Preparacion, raw.get("preparacion"), "preparacion"),
        split=_seccion(Split, raw.get("split"), "split"),
        plan=_seccion(Plan, raw.get("plan"), "plan"),
        tuning=_seccion(Tuning, raw.get("tuning"), "tuning"),
        modelos=modelos,
        seed=int(raw.get("seed", 42)),
        excluir_dias_incompletos_eval=bool(raw.get("excluir_dias_incompletos_eval", True)),
        path=config_path,
    )
    _validar(config)
    return config


def _validar(config: Config) -> None:
    if not 0 < config.split.test < 1 or not 0 <= config.split.validacion < 1:
        raise ConfigError("split.test y split.validacion deben estar entre 0 y 1.")
    if config.split.test + config.split.validacion >= 0.9:
        raise ConfigError("split.test + split.validacion deja muy poco para entrenar.")
    if config.plan.max_ciclos < 1:
        raise ConfigError("plan.max_ciclos debe ser >= 1.")
    desconocidos = set(config.modelos) - {"random_forest", "xgboost", "svr", "mlp"}
    if desconocidos:
        raise ConfigError(f"Modelos no soportados: {sorted(desconocidos)}")
