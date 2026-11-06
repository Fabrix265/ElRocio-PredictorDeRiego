from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when the YAML configuration is invalid."""


@dataclass
class SourceConfig:
    type: str = "excel"
    path: Path | None = None
    sheet: str | None = None
    sep: str = ","
    encoding: str = "utf-8"
    column_map: dict[str, str] = field(default_factory=dict)


@dataclass
class DataConfig:
    source: SourceConfig = field(default_factory=SourceConfig)
    turno_file: Path | None = None
    ciclos_file: Path | None = None
    columns_file: Path | None = None
    date_column: str = "Fecha"
    group_column: str = "Turno"
    id_columns: list[str] = field(
        default_factory=lambda: ["Fecha", "Fundo", "Modulo", "Turno"]
    )
    categorical_features: list[str] = field(
        default_factory=lambda: ["Fundo", "Modulo", "Turno"]
    )
    numeric_features: list[str] = field(default_factory=list)
    environmental_features: list[str] = field(default_factory=list)
    max_cycles: int = 5
    tail_class: int = 5
    cycle_column: str = "Ciclo"
    target_cycle_columns: list[str] = field(
        default_factory=lambda: ["riego_m3ha", "inicio_min", "duracion_min"]
    )
    incomplete_column: str = "dia_incompleto"
    exclude_incomplete_from_eval: bool = True
    nro_ciclo_column: str = "Nro_ciclo"
    cycle_volume_column: str = "Riego_ciclo_m3"
    start_column: str = "Hora_inicio"
    end_column: str = "Hora_fin"
    drop_columns: list[str] = field(default_factory=list)


@dataclass
class SplitConfig:
    strategy: str = "temporal"
    group_column: str | None = None
    test_size: float = 0.2
    validation_size: float = 0.15
    gap_days: int = 3
    random_state: int = 42


@dataclass
class TargetsConfig:
    n_ciclos_column: str = "N_ciclos"
    n_ciclos_classes: list[int] = field(default_factory=lambda: [1, 2, 3])
    total_column: str = "Riego_total_m3"
    direct_total_model: bool = False


@dataclass
class ModelConfig:
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    early_stopping: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationConfig:
    regression_metrics: list[str] = field(
        default_factory=lambda: [
            "rmse",
            "mae",
            "r2",
            "mbe",
            "pearson_r",
            "kge",
            "nse",
            "pbias",
            "smape",
            "willmott_d",
            "medae",
            "max_error",
        ]
    )
    classification_metrics: list[str] = field(
        default_factory=lambda: [
            "accuracy",
            "balanced_accuracy",
            "f1_macro",
            "cohen_kappa",
        ]
    )
    generate_plots: bool = True
    generate_excel: bool = True
    max_gantt_turnos: int = 6
    top_errors: int = 20


@dataclass
class ScheduleConfig:
    min_gap_min: float = 0.0
    end_mode: str = "derived"


@dataclass
class TuningConfig:
    enabled: bool = False
    n_iter: int = 30
    cv_splits: int = 4
    n_jobs: int = -1
    scoring_classification: str = "f1_macro"
    scoring_regression: str = "neg_root_mean_squared_error"
    target: str = "n_ciclos"


@dataclass
class RunConfig:
    name: str = "riego"
    seed: int = 42
    config_path: Path | None = None
    reports_dir: Path | None = None
    models_dir: Path | None = None
    data: DataConfig = field(default_factory=DataConfig)
    split: SplitConfig = field(default_factory=SplitConfig)
    targets: TargetsConfig = field(default_factory=TargetsConfig)
    models: dict[str, ModelConfig] = field(default_factory=dict)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    tuning: TuningConfig = field(default_factory=TuningConfig)
