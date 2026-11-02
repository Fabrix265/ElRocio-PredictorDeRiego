from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from riego_ml.config.schema import (
    ConfigError,
    DataConfig,
    EvaluationConfig,
    ModelConfig,
    RunConfig,
    ScheduleConfig,
    SourceConfig,
    SplitConfig,
    TargetsConfig,
)
from riego_ml.settings import (
    DEFAULT_TRAIN_CONFIG,
    MODELS_DIR,
    PROJECT_ROOT,
    REPORTS_DIR,
    RANDOM_STATE,
)


def _resolve_path(value: str | Path | None, base: Path = PROJECT_ROOT) -> Path | None:
    if value is None:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"'{name}' debe ser un objeto YAML.")
    return value


def _require_list(value: Any, name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ConfigError(f"'{name}' debe ser una lista.")
    return value


def _load_source(raw: dict[str, Any]) -> SourceConfig:
    source_type = str(raw.get("type", "excel")).lower()
    if source_type not in {"excel", "csv", "parquet"}:
        raise ConfigError(
            f"data.source.type no soportado: {source_type}. Usa excel, csv o parquet."
        )
    column_map = raw.get("column_map") or {}
    if not isinstance(column_map, dict):
        raise ConfigError("data.source.column_map debe ser un objeto YAML.")
    path = _resolve_path(raw.get("path"))
    if path is None:
        raise ConfigError("data.source.path es obligatorio.")
    if not path.exists():
        raise ConfigError(f"No existe el archivo de datos: {path}")
    return SourceConfig(
        type=source_type,
        path=path,
        sheet=raw.get("sheet"),
        sep=str(raw.get("sep", ",")),
        encoding=str(raw.get("encoding", "utf-8")),
        column_map={str(k): str(v) for k, v in column_map.items()},
    )


def _load_data(raw: dict[str, Any]) -> DataConfig:
    source = _load_source(_require_mapping(raw.get("source", {}), "data.source"))
    max_cycles = int(raw.get("max_cycles", 3))
    if max_cycles < 1:
        raise ConfigError("data.max_cycles debe ser >= 1.")
    return DataConfig(
        source=source,
        date_column=str(raw.get("date_column", "Fecha")),
        group_column=str(raw.get("group_column", "Turno")),
        id_columns=[str(v) for v in _require_list(raw.get("id_columns"), "data.id_columns")]
        or ["Fecha", "Fundo", "Modulo", "Turno"],
        categorical_features=[
            str(v)
            for v in _require_list(
                raw.get("categorical_features"), "data.categorical_features"
            )
        ]
        or ["Fundo", "Modulo", "Turno"],
        numeric_features=[
            str(v)
            for v in _require_list(raw.get("numeric_features"), "data.numeric_features")
        ],
        environmental_features=[
            str(v)
            for v in _require_list(
                raw.get("environmental_features"), "data.environmental_features"
            )
        ],
        max_cycles=max_cycles,
        nro_ciclo_column=str(raw.get("nro_ciclo_column", "Nro_ciclo")),
        cycle_volume_column=str(raw.get("cycle_volume_column", "Riego_ciclo_m3")),
        start_column=str(raw.get("start_column", "Hora_inicio")),
        end_column=str(raw.get("end_column", "Hora_fin")),
        drop_columns=[
            str(v)
            for v in _require_list(raw.get("drop_columns"), "data.drop_columns")
        ],
    )


def _load_split(raw: dict[str, Any]) -> SplitConfig:
    test_size = float(raw.get("test_size", 0.2))
    validation_size = float(raw.get("validation_size", 0.15))
    if not 0 < test_size < 1:
        raise ConfigError("split.test_size debe estar entre 0 y 1.")
    if not 0 <= validation_size < 1 - test_size:
        raise ConfigError(
            "split.validation_size debe ser >= 0 y menor que 1 - split.test_size."
        )
    return SplitConfig(
        strategy=str(raw.get("strategy", "group_shuffle")),
        test_size=test_size,
        validation_size=validation_size,
        random_state=int(raw.get("random_state", RANDOM_STATE)),
    )


def _load_targets(raw: dict[str, Any]) -> TargetsConfig:
    classes = [int(v) for v in _require_list(raw.get("n_ciclos_classes"), "targets.n_ciclos_classes")]
    if not classes:
        classes = [1, 2, 3]
    return TargetsConfig(
        n_ciclos_column=str(raw.get("n_ciclos_column", "N_ciclos")),
        n_ciclos_classes=classes,
        total_column=str(raw.get("total_column", "Riego_total_m3")),
        direct_total_model=bool(raw.get("direct_total_model", False)),
    )


def _load_models(raw: dict[str, Any]) -> dict[str, ModelConfig]:
    models_raw = _require_mapping(raw, "models")
    models: dict[str, ModelConfig] = {}
    for name, cfg in models_raw.items():
        cfg = _require_mapping(cfg, f"models.{name}")
        models[str(name)] = ModelConfig(
            enabled=bool(cfg.get("enabled", True)),
            params=dict(cfg.get("params") or {}),
            early_stopping=dict(cfg.get("early_stopping") or {}),
        )
    if not models:
        raise ConfigError("Debes configurar al menos un modelo en 'models'.")
    return models


def _load_evaluation(raw: dict[str, Any]) -> EvaluationConfig:
    return EvaluationConfig(
        regression_metrics=[
            str(v)
            for v in _require_list(
                raw.get("regression_metrics"), "evaluation.regression_metrics"
            )
        ]
        or EvaluationConfig().regression_metrics,
        classification_metrics=[
            str(v)
            for v in _require_list(
                raw.get("classification_metrics"), "evaluation.classification_metrics"
            )
        ]
        or EvaluationConfig().classification_metrics,
        generate_plots=bool(raw.get("generate_plots", True)),
        generate_excel=bool(raw.get("generate_excel", True)),
        max_gantt_turnos=int(raw.get("max_gantt_turnos", 6)),
        top_errors=int(raw.get("top_errors", 20)),
    )


def _load_schedule(raw: dict[str, Any]) -> ScheduleConfig:
    return ScheduleConfig(
        min_gap_min=float(raw.get("min_gap_min", 0.0)),
        end_mode=str(raw.get("end_mode", "derived")),
    )


def load_config(path: str | Path | None = None) -> RunConfig:
    config_path = _resolve_path(path) if path is not None else DEFAULT_TRAIN_CONFIG
    if config_path is None or not config_path.exists():
        raise ConfigError(f"No existe el archivo de configuración: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    if not isinstance(raw, dict):
        raise ConfigError("El YAML raíz debe ser un objeto.")

    data = _load_data(_require_mapping(raw.get("data", {}), "data"))
    split = _load_split(_require_mapping(raw.get("split", {}), "split"))
    targets = _load_targets(_require_mapping(raw.get("targets", {}), "targets"))
    models = _load_models(_require_mapping(raw.get("models", {}), "models"))
    evaluation = _load_evaluation(
        _require_mapping(raw.get("evaluation", {}), "evaluation")
    )
    schedule = _load_schedule(_require_mapping(raw.get("schedule", {}), "schedule"))

    return RunConfig(
        name=str(raw.get("name", "riego")),
        seed=int(raw.get("seed", split.random_state)),
        config_path=config_path,
        reports_dir=_resolve_path(raw.get("reports_dir", str(REPORTS_DIR))),
        models_dir=_resolve_path(raw.get("models_dir", str(MODELS_DIR))),
        data=data,
        split=split,
        targets=targets,
        models=models,
        evaluation=evaluation,
        schedule=schedule,
    )
