from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from riego_ml.config.schema import RunConfig
from riego_ml.data.validation import DataValidationError

DATE_FEATURES = ["anio", "mes", "dia", "dia_anio", "dia_semana", "semana_iso"]
TARGET_PREFIXES = (
    "Riego_ciclo_",
    "Hora_inicio_",
    "Hora_fin_",
    "Tiempo_ciclo_",
)


@dataclass
class TargetSpec:
    name: str
    column: str
    kind: Literal["classification", "regression"]
    classes: list[int] | None = None
    slot: int | None = None
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def build_target_specs(config: RunConfig) -> list[TargetSpec]:
    targets = config.targets
    specs: list[TargetSpec] = [
        TargetSpec(
            name="n_ciclos",
            column=targets.n_ciclos_column,
            kind="classification",
            classes=list(targets.n_ciclos_classes),
            description="Número de ciclos de riego del turno.",
        )
    ]
    for slot in range(1, config.data.max_cycles + 1):
        specs.extend(
            [
                TargetSpec(
                    name=f"Riego_ciclo_{slot}_m3",
                    column=f"Riego_ciclo_{slot}_m3",
                    kind="regression",
                    slot=slot,
                    description=f"Volumen del ciclo {slot} (m3).",
                ),
                TargetSpec(
                    name=f"Hora_inicio_{slot}_min",
                    column=f"Hora_inicio_{slot}_min",
                    kind="regression",
                    slot=slot,
                    description=f"Hora de inicio del ciclo {slot} en minutos desde medianoche.",
                ),
                TargetSpec(
                    name=f"Tiempo_ciclo_{slot}_min",
                    column=f"Tiempo_ciclo_{slot}_min",
                    kind="regression",
                    slot=slot,
                    description=f"Duración del ciclo {slot} en minutos.",
                ),
            ]
        )
    if targets.direct_total_model:
        specs.append(
            TargetSpec(
                name="Riego_total_m3",
                column=targets.total_column,
                kind="regression",
                description="Volumen total del turno (m3), modelo directo opcional.",
            )
        )
    return specs


def target_columns(specs: list[TargetSpec]) -> list[str]:
    return [spec.column for spec in specs]


def build_v2_turno_specs(config: RunConfig) -> list[TargetSpec]:
    return [
        TargetSpec(
            name="n_ciclos",
            column="n_ciclos_clase",
            kind="classification",
            classes=list(config.targets.n_ciclos_classes),
            description=(
                "Número de ciclos del turno. La cola se agrupa en la clase "
                f"{config.data.tail_class} (5+)."
            ),
            metadata={"tail_class": config.data.tail_class},
        )
    ]


def build_v2_cycle_specs(config: RunConfig) -> list[TargetSpec]:
    specs: list[TargetSpec] = []
    for target in config.data.target_cycle_columns:
        for slot in range(1, config.data.max_cycles + 1):
            specs.append(
                TargetSpec(
                    name=f"{target}_ciclo_{slot}",
                    column=f"target__{target}__{slot}",
                    kind="regression",
                    slot=slot,
                    description=f"{target} del ciclo {slot}.",
                    metadata={"target": target, "slot": slot},
                )
            )
    return specs


def _is_leakage_column(column: str, config: RunConfig) -> bool:
    if column in config.data.id_columns:
        return True
    if column == config.data.date_column:
        return True
    if column in config.data.drop_columns:
        return True
    if column in {
        config.targets.n_ciclos_column,
        config.targets.total_column,
        config.data.nro_ciclo_column,
        config.data.cycle_volume_column,
        config.data.start_column,
        config.data.end_column,
    }:
        return True
    return any(column.startswith(prefix) for prefix in TARGET_PREFIXES)


def build_feature_columns(
    turno_df: pd.DataFrame, config: RunConfig, specs: list[TargetSpec]
) -> tuple[list[str], list[str], list[str]]:
    data = config.data
    categorical = list(dict.fromkeys(data.categorical_features))
    missing_categorical = [c for c in categorical if c not in turno_df.columns]
    if missing_categorical:
        raise DataValidationError(
            "Faltan features categóricas configuradas: "
            + ", ".join(missing_categorical)
        )

    numeric: list[str] = []
    for column in data.numeric_features:
        if column not in turno_df.columns:
            raise DataValidationError(
                f"La feature numérica configurada no existe en el dataset: {column}"
            )
        numeric.append(column)

    for column in data.environmental_features:
        for suffix in ("mean", "min", "max", "std"):
            generated = f"{column}_{suffix}"
            if generated not in turno_df.columns:
                raise DataValidationError(
                    f"No se generó el agregado ambiental esperado: {generated}"
                )
            numeric.append(generated)

    numeric.extend([column for column in DATE_FEATURES if column in turno_df.columns])
    if "Turno_orden" in turno_df.columns:
        numeric.append("Turno_orden")

    numeric = [c for c in dict.fromkeys(numeric) if c not in categorical]
    target_cols = set(target_columns(specs))

    features: list[str] = []
    for column in [*categorical, *numeric]:
        if column in target_cols:
            continue
        if column in categorical:
            features.append(column)
            continue
        if _is_leakage_column(column, config):
            continue
        features.append(column)

    if not features:
        raise DataValidationError("No quedaron features después de quitar los targets.")
    return features, categorical, numeric


def split_xy(
    turno_df: pd.DataFrame, feature_columns: list[str], specs: list[TargetSpec]
) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    X = turno_df[feature_columns].copy()
    y = {spec.name: turno_df[spec.column].copy() for spec in specs}
    return X, y
