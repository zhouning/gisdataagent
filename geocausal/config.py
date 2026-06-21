from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from data_agent.scca.specs import StudySpec

from .errors import GeoCausalConfigError

SUPPORTED_FORMATS = {
    ".csv": "csv",
    ".gpkg": "gpkg",
    ".geojson": "geojson",
    ".json": "geojson",
    ".shp": "shp",
}


@dataclass(frozen=True)
class InputConfig:
    path: Path
    format: str
    x: str | None = None
    y: str | None = None
    lon: str | None = None
    lat: str | None = None


@dataclass(frozen=True)
class VariablesConfig:
    exposure: str
    outcome: str
    unit_id: str = "_gc_unit_id"
    baseline_outcome: str | None = None
    population: str | None = None
    confounders: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ContextConfig:
    columns: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ExposureTrimConfig:
    lower_quantile: float
    upper_quantile: float


@dataclass(frozen=True)
class PreprocessingConfig:
    exposure_trim: ExposureTrimConfig | None = None


@dataclass(frozen=True)
class PlaceboExposureConfig:
    name: str
    column: str
    role: str = "placebo"
    expected_relation: str = "weaker_than_main"

    def to_robustness_test(self) -> dict[str, str]:
        return {
            "test_name": self.name,
            "exposure": self.column,
            "role": self.role,
            "expected_relation": self.expected_relation,
        }


@dataclass(frozen=True)
class BootstrapConfig:
    group_column: str | None = None
    n_replicates: int = 200


@dataclass(frozen=True)
class RobustnessConfig:
    placebo_exposures: tuple[PlaceboExposureConfig, ...] = field(default_factory=tuple)
    bootstrap: BootstrapConfig = field(default_factory=BootstrapConfig)


@dataclass(frozen=True)
class TargetOutcomeConfig:
    name: str
    value: float


@dataclass(frozen=True)
class TargetsConfig:
    outcome_values: tuple[TargetOutcomeConfig, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OutputConfig:
    directory: Path


@dataclass(frozen=True)
class GeoCausalConfig:
    case_name: str
    input: InputConfig
    variables: VariablesConfig
    context: ContextConfig
    preprocessing: PreprocessingConfig
    robustness: RobustnessConfig
    targets: TargetsConfig
    output: OutputConfig
    config_path: Path

    def resolve_input_path(self) -> Path:
        if self.input.path.is_absolute():
            return self.input.path
        return (self.config_path.parent / self.input.path).resolve()

    def resolve_output_dir(self) -> Path:
        if self.output.directory.is_absolute():
            return self.output.directory
        return (self.config_path.parent / self.output.directory).resolve()

    def to_study_spec(self) -> StudySpec:
        coordinate_columns: tuple[str, str] | None = None
        if self.input.x and self.input.y:
            coordinate_columns = (self.input.x, self.input.y)
        elif self.input.lon and self.input.lat:
            coordinate_columns = (self.input.lon, self.input.lat)
        return StudySpec(
            name=self.case_name,
            unit_id=self.variables.unit_id,
            exposure=self.variables.exposure,
            outcome=self.variables.outcome,
            baseline_outcome=self.variables.baseline_outcome,
            population=self.variables.population,
            confounders=self.variables.confounders,
            context_columns=self.context.columns,
            coordinate_columns=coordinate_columns,
            subgroup_column=self.robustness.bootstrap.group_column,
        )


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GeoCausalConfigError(f"{name} must be a mapping.")
    return value


def _require_text(mapping: dict[str, Any], key: str, owner: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise GeoCausalConfigError(f"{owner}.{key} is required.")
    return value.strip()


def _optional_text(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GeoCausalConfigError(f"{key} must be a non-empty string when provided.")
    return value.strip()


def _text_tuple(value: Any, owner: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise GeoCausalConfigError(f"{owner} must be a list of column names.")
    return tuple(item.strip() for item in value)


def _optional_float(mapping: dict[str, Any], key: str, owner: str) -> float | None:
    value = mapping.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GeoCausalConfigError(f"{owner}.{key} must be a number when provided.")
    return float(value)


def _infer_format(path: Path, explicit: str | None) -> str:
    if explicit:
        normalized = explicit.lower().lstrip(".")
        if normalized == "json":
            return "geojson"
        if normalized in {"csv", "gpkg", "geojson", "shp"}:
            return normalized
        raise GeoCausalConfigError(f"Unsupported input format: {explicit}")
    try:
        return SUPPORTED_FORMATS[path.suffix.lower()]
    except KeyError as exc:
        raise GeoCausalConfigError(f"Unsupported input format: {path.suffix or '<none>'}") from exc


def load_config(path: str | Path) -> GeoCausalConfig:
    config_path = Path(path).resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise GeoCausalConfigError(f"Invalid YAML in config file: {config_path}") from exc
    except OSError as exc:
        raise GeoCausalConfigError(f"Cannot read config file: {config_path}") from exc
    if raw is None:
        raise GeoCausalConfigError("Config file is empty.")
    root = _require_mapping(raw, "config")

    case_name = _require_text(root, "case_name", "config")
    input_raw = _require_mapping(root.get("input"), "input")
    variables_raw = _require_mapping(root.get("variables"), "variables")
    context_raw = _require_mapping(root.get("context", {}), "context")
    preprocessing_raw = _require_mapping(root.get("preprocessing", {}), "preprocessing")
    robustness_raw = _require_mapping(root.get("robustness", {}), "robustness")
    targets_raw = _require_mapping(root.get("targets", {}), "targets")
    output_raw = _require_mapping(root.get("output"), "output")

    input_path = Path(_require_text(input_raw, "path", "input"))
    input_config = InputConfig(
        path=input_path,
        format=_infer_format(input_path, _optional_text(input_raw, "format")),
        x=_optional_text(input_raw, "x"),
        y=_optional_text(input_raw, "y"),
        lon=_optional_text(input_raw, "lon"),
        lat=_optional_text(input_raw, "lat"),
    )
    coordinate_keys = {
        key
        for key, value in {
            "x": input_config.x,
            "y": input_config.y,
            "lon": input_config.lon,
            "lat": input_config.lat,
        }.items()
        if value
    }
    if coordinate_keys not in (set(), {"x", "y"}, {"lon", "lat"}):
        raise GeoCausalConfigError("coordinate columns must be provided as x/y or lon/lat pairs.")

    variables = VariablesConfig(
        exposure=_require_text(variables_raw, "exposure", "variables"),
        outcome=_require_text(variables_raw, "outcome", "variables"),
        unit_id=_optional_text(variables_raw, "unit_id") or "_gc_unit_id",
        baseline_outcome=_optional_text(variables_raw, "baseline_outcome"),
        population=_optional_text(variables_raw, "population"),
        confounders=_text_tuple(variables_raw.get("confounders"), "variables.confounders"),
    )

    trim_raw = preprocessing_raw.get("exposure_trim")
    exposure_trim = None
    if trim_raw is not None:
        trim_mapping = _require_mapping(trim_raw, "preprocessing.exposure_trim")
        lower_quantile = _optional_float(
            trim_mapping,
            "lower_quantile",
            "preprocessing.exposure_trim",
        )
        upper_quantile = _optional_float(
            trim_mapping,
            "upper_quantile",
            "preprocessing.exposure_trim",
        )
        if lower_quantile is None or upper_quantile is None:
            raise GeoCausalConfigError(
                "preprocessing.exposure_trim.lower_quantile and upper_quantile are required."
            )
        if not (0.0 <= lower_quantile < upper_quantile <= 1.0):
            raise GeoCausalConfigError(
                "preprocessing.exposure_trim quantiles must satisfy 0 <= lower < upper <= 1."
            )
        exposure_trim = ExposureTrimConfig(
            lower_quantile=lower_quantile,
            upper_quantile=upper_quantile,
        )

    placebo_items = robustness_raw.get("placebo_exposures", [])
    if not isinstance(placebo_items, list):
        raise GeoCausalConfigError("robustness.placebo_exposures must be a list.")
    placebo_exposures: list[PlaceboExposureConfig] = []
    for index, item in enumerate(placebo_items):
        item_raw = _require_mapping(item, f"robustness.placebo_exposures[{index}]")
        column = _require_text(item_raw, "column", f"robustness.placebo_exposures[{index}]")
        placebo_exposures.append(
            PlaceboExposureConfig(
                name=_optional_text(item_raw, "name") or column,
                column=column,
                role=_optional_text(item_raw, "role") or "placebo",
                expected_relation=_optional_text(item_raw, "expected_relation") or "weaker_than_main",
            )
        )

    bootstrap_raw = _require_mapping(robustness_raw.get("bootstrap", {}), "robustness.bootstrap")
    n_replicates = bootstrap_raw.get("n_replicates", 200)
    if isinstance(n_replicates, bool) or not isinstance(n_replicates, int) or n_replicates <= 0:
        raise GeoCausalConfigError("robustness.bootstrap.n_replicates must be a positive integer.")

    target_items = targets_raw.get("outcome_values", [])
    if not isinstance(target_items, list):
        raise GeoCausalConfigError("targets.outcome_values must be a list.")
    outcome_values: list[TargetOutcomeConfig] = []
    for index, item in enumerate(target_items):
        item_raw = _require_mapping(item, f"targets.outcome_values[{index}]")
        value = _optional_float(item_raw, "value", f"targets.outcome_values[{index}]")
        if value is None:
            raise GeoCausalConfigError(f"targets.outcome_values[{index}].value is required.")
        outcome_values.append(
            TargetOutcomeConfig(
                name=_optional_text(item_raw, "name") or f"target_{index + 1}",
                value=value,
            )
        )

    return GeoCausalConfig(
        case_name=case_name,
        input=input_config,
        variables=variables,
        context=ContextConfig(columns=_text_tuple(context_raw.get("columns"), "context.columns")),
        preprocessing=PreprocessingConfig(exposure_trim=exposure_trim),
        robustness=RobustnessConfig(
            placebo_exposures=tuple(placebo_exposures),
            bootstrap=BootstrapConfig(
                group_column=_optional_text(bootstrap_raw, "group_column"),
                n_replicates=n_replicates,
            ),
        ),
        targets=TargetsConfig(outcome_values=tuple(outcome_values)),
        output=OutputConfig(directory=Path(_require_text(output_raw, "directory", "output"))),
        config_path=config_path,
    )


def required_columns(config: GeoCausalConfig) -> set[str]:
    columns = {
        config.variables.exposure,
        config.variables.outcome,
        *config.variables.confounders,
        *config.context.columns,
    }
    if config.variables.unit_id != "_gc_unit_id":
        columns.add(config.variables.unit_id)
    if config.variables.baseline_outcome:
        columns.add(config.variables.baseline_outcome)
    if config.variables.population:
        columns.add(config.variables.population)
    if config.input.x:
        columns.add(config.input.x)
    if config.input.y:
        columns.add(config.input.y)
    if config.input.lon:
        columns.add(config.input.lon)
    if config.input.lat:
        columns.add(config.input.lat)
    if config.robustness.bootstrap.group_column:
        columns.add(config.robustness.bootstrap.group_column)
    for placebo in config.robustness.placebo_exposures:
        columns.add(placebo.column)
    return {column for column in columns if column}


def validate_config(config: GeoCausalConfig, available_columns: set[str] | None = None) -> list[str]:
    warnings: list[str] = []
    if config.input.format == "csv":
        has_xy = bool(config.input.x and config.input.y)
        has_lon_lat = bool(config.input.lon and config.input.lat)
        if not has_xy and not has_lon_lat:
            warnings.append(
                "CSV input has no coordinate columns; geometry-derived bootstrap groups are unavailable."
            )
    if available_columns is not None:
        missing = sorted(required_columns(config) - set(available_columns))
        if missing:
            raise GeoCausalConfigError(f"Missing required columns: {', '.join(missing)}")
    return warnings
