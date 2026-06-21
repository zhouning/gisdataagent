from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import re

import pandas as pd
import yaml

from .config import load_config
from .pipeline import run_analysis


@dataclass(frozen=True)
class AnalysisRequest:
    case_name: str
    input_path: Path
    output_dir: Path
    exposure: str
    outcome: str
    unit_id: str | None = None
    baseline_outcome: str | None = None
    population: str | None = None
    confounders: tuple[str, ...] = field(default_factory=tuple)
    context_columns: tuple[str, ...] = field(default_factory=tuple)
    coordinate_columns: tuple[str, str] | None = None
    bootstrap_group: str | None = None
    placebo_exposures: tuple[str, ...] = field(default_factory=tuple)
    lower_exposure_quantile: float | None = None
    upper_exposure_quantile: float | None = None
    target_outcomes: tuple[float, ...] = field(default_factory=tuple)
    bootstrap_replicates: int = 200


def _clean_strings(values: tuple[str, ...]) -> list[str]:
    return [value.strip() for value in values if value and value.strip()]


def analysis_config_dict(request: AnalysisRequest) -> dict[str, Any]:
    input_block: dict[str, Any] = {"path": str(request.input_path)}
    if request.coordinate_columns:
        input_block["x"] = request.coordinate_columns[0]
        input_block["y"] = request.coordinate_columns[1]

    variables: dict[str, Any] = {
        "exposure": request.exposure,
        "outcome": request.outcome,
    }
    if request.unit_id:
        variables["unit_id"] = request.unit_id
    if request.baseline_outcome:
        variables["baseline_outcome"] = request.baseline_outcome
    if request.population:
        variables["population"] = request.population
    confounders = _clean_strings(request.confounders)
    if confounders:
        variables["confounders"] = confounders

    config: dict[str, Any] = {
        "case_name": request.case_name,
        "input": input_block,
        "variables": variables,
        "output": {"directory": str(request.output_dir)},
    }

    context_columns = _clean_strings(request.context_columns)
    if context_columns:
        config["context"] = {"columns": context_columns}

    if (
        request.lower_exposure_quantile is not None
        or request.upper_exposure_quantile is not None
    ):
        config["preprocessing"] = {
            "exposure_trim": {
                "lower_quantile": request.lower_exposure_quantile
                if request.lower_exposure_quantile is not None
                else 0.0,
                "upper_quantile": request.upper_exposure_quantile
                if request.upper_exposure_quantile is not None
                else 1.0,
            }
        }

    robustness: dict[str, Any] = {
        "bootstrap": {"n_replicates": request.bootstrap_replicates}
    }
    if request.bootstrap_group:
        robustness["bootstrap"]["group_column"] = request.bootstrap_group
    placebo_exposures = _clean_strings(request.placebo_exposures)
    if placebo_exposures:
        robustness["placebo_exposures"] = [
            {
                "name": column,
                "column": column,
                "role": "placebo",
                "expected_relation": "weaker_than_main",
            }
            for column in placebo_exposures
        ]
    config["robustness"] = robustness

    if request.target_outcomes:
        config["targets"] = {
            "outcome_values": [
                {"name": f"target_{value:g}", "value": float(value)}
                for value in request.target_outcomes
            ]
        }
    return config


def write_analysis_config(request: AnalysisRequest) -> Path:
    request.output_dir.mkdir(parents=True, exist_ok=True)
    config_path = request.output_dir / "analysis.yaml"
    config_path.write_text(
        yaml.safe_dump(
            analysis_config_dict(request),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return config_path


def run_scca_analysis(request: AnalysisRequest) -> dict[str, Any]:
    config_path = write_analysis_config(request)
    return run_analysis(load_config(config_path))


def _safe_field_token(value: object) -> str:
    token = re.sub(r"[^0-9A-Za-z_]+", "_", str(value).strip()).strip("_").lower()
    if not token:
        return "target"
    if token[0].isdigit():
        return f"t_{token}"
    return token


def _ensure_join_unit_id(frame: pd.DataFrame, unit_id_field: str | None) -> tuple[pd.DataFrame, str]:
    joined = frame.copy()
    if unit_id_field:
        if unit_id_field not in joined.columns:
            raise ValueError(f"Unit ID field is missing from input CSV: {unit_id_field}")
        joined[unit_id_field] = joined[unit_id_field].astype(str)
        return joined, unit_id_field

    generated = "_gc_unit_id"
    if generated not in joined.columns:
        joined.insert(0, generated, [str(index) for index in range(1, len(joined) + 1)])
    else:
        joined[generated] = joined[generated].astype(str)
    return joined, generated


def build_analysis_joined_table(
    *,
    input_csv: Path,
    target_exposures_csv: Path,
    output_csv: Path,
    unit_id_field: str | None = None,
    method: str = "erf_delta_anchor",
) -> Path:
    """Create a wide, one-row-per-unit analysis table for GIS joins and notebooks."""
    source_dtype = {unit_id_field: "string"} if unit_id_field else None
    source = pd.read_csv(input_csv, encoding="utf-8-sig", dtype=source_dtype)
    source, join_column = _ensure_join_unit_id(source, unit_id_field)
    targets = pd.read_csv(
        target_exposures_csv,
        encoding="utf-8-sig",
        dtype={"unit_id": "string"},
    )
    required = {"unit_id", "method", "target_name"}
    missing = required.difference(targets.columns)
    if missing:
        raise ValueError(f"Target exposure CSV is missing columns: {', '.join(sorted(missing))}")

    selected = targets.loc[targets["method"].astype(str) == method].copy()
    selected["unit_id"] = selected["unit_id"].astype(str)
    metric_columns = [
        column
        for column in selected.columns
        if column not in {"unit_id", "method", "target_name"}
    ]
    for target_name in selected["target_name"].dropna().astype(str).drop_duplicates():
        token = _safe_field_token(target_name)
        block = selected.loc[selected["target_name"].astype(str) == target_name, ["unit_id", *metric_columns]]
        block = block.drop_duplicates(subset=["unit_id"], keep="first")
        block = block.rename(
            columns={
                column: f"gc_{token}_{_safe_field_token(column)}"
                for column in metric_columns
            }
        )
        source = source.merge(block, how="left", left_on=join_column, right_on="unit_id")
        if "unit_id" in source.columns and "unit_id" != join_column:
            source = source.drop(columns=["unit_id"])

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    source.to_csv(output_csv, index=False, encoding="utf-8-sig")
    return output_csv
