#!/usr/bin/env python3
"""Audit whether sealed historical artifacts support a contextual expert gate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from data_agent.uwm.geospatial_kernel_v2.action_innovation_transition import (
    action_innovation_transition_parameters_from_dict,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    from scripts import (
        evaluate_geospatial_kernel_online_expert_traditional_baselines as traditional,
    )
    from scripts import evaluate_geospatial_kernel_physical_online_expert_blend as blend
    from scripts import evaluate_geospatial_kernel_physical_online_residual_adaptation as jpp
    from scripts import (
        evaluate_geospatial_kernel_physical_online_residual_adaptation_cross_system as center,
    )
else:
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    import evaluate_geospatial_kernel_online_expert_traditional_baselines as traditional
    import evaluate_geospatial_kernel_physical_online_expert_blend as blend
    import evaluate_geospatial_kernel_physical_online_residual_adaptation as jpp
    import evaluate_geospatial_kernel_physical_online_residual_adaptation_cross_system as center

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDITOR_PATH = Path(__file__).resolve()
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_online_expert_context_sufficiency_audit.json"
)
SCHEMA = "gwm.geotransport.online_expert_context_sufficiency_audit.v2"
WINDOW_NAMES = traditional.WINDOW_NAMES
HORIZONS = traditional.HORIZONS
PREDICTION_DERIVED_FEATURES = (
    "expert_delta_scaled",
    "absolute_expert_delta_scaled",
    "latest_physical_residual_scaled",
    "raw_physical_target_change_scaled",
    "v4_target_change_scaled",
)
RETROSPECTIVE_HYDROLOGIC_FEATURES = (
    "action_release_scaled",
    "effective_action_change_scaled",
    "absolute_effective_action_change_scaled",
    "path_lateral_inflow_scaled",
)
EXPLICIT_CONTEXT_FIELDS = {
    "reservoir_release": (
        "reservoir_release_m3s",
        "release_m3s",
        "action_release_m3s",
    ),
    "nwm_lateral_inflow": (
        "nwm_lateral_inflow_m3s",
        "q_lateral_m3s",
        "forcing_m3s",
    ),
    "precipitation": ("precipitation_mm", "rainfall_mm"),
    "soil_moisture_or_saturation": (
        "soil_moisture",
        "soil_saturation",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jpp-v4-report", type=Path, default=jpp.DEFAULT_REPORT)
    parser.add_argument("--center-v4-report", type=Path, default=center.DEFAULT_REPORT)
    parser.add_argument("--v5-report", type=Path, default=blend.DEFAULT_REPORT)
    parser.add_argument("--traditional-report", type=Path, default=traditional.DEFAULT_REPORT)
    parser.add_argument("--cross-system-report", type=Path, default=cross.DEFAULT_REPORT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_online_expert_context_sufficiency_audit(
    *,
    jpp_v4_report_path: Path = jpp.DEFAULT_REPORT,
    center_v4_report_path: Path = center.DEFAULT_REPORT,
    v5_report_path: Path = blend.DEFAULT_REPORT,
    traditional_report_path: Path = traditional.DEFAULT_REPORT,
    cross_system_report_path: Path = cross.DEFAULT_REPORT,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Measure issue-time feature coverage and descriptive loss association."""

    jpp_body, jpp_report = _load_report(
        jpp_v4_report_path,
        schema=jpp.SCHEMA,
        status="causal_online_residual_adaptation_posthoc_complete",
    )
    center_body, center_report = _load_report(
        center_v4_report_path,
        schema=center.SCHEMA,
        status="fixed_v4_center_hill_cross_system_posthoc_complete",
    )
    v5_body, v5_report = _load_report(
        v5_report_path,
        schema=blend.SCHEMA,
        status="physical_first_online_expert_blend_posthoc_complete",
    )
    traditional_body, traditional_report = _load_report(
        traditional_report_path,
        schema=traditional.SCHEMA,
        status="online_expert_traditional_baselines_posthoc_complete",
    )
    cross_body, cross_report = _load_cross_system_report(cross_system_report_path)
    context_windows, context_sources = _load_retrospective_context_windows(cross_report)
    v4_descriptors = {
        "j_percy_priest_primary": jpp_report["outputs"]["primary_predictions"],
        "j_percy_priest_replication": jpp_report["outputs"]["replication_predictions"],
        "center_hill_primary": center_report["outputs"]["primary_predictions"],
        "center_hill_replication": center_report["outputs"]["replication_predictions"],
    }
    v5_descriptors = v5_report["outputs"]
    traditional_descriptors = traditional_report["outputs"]
    if (
        set(v4_descriptors) != set(WINDOW_NAMES)
        or set(v5_descriptors) != set(WINDOW_NAMES)
        or set(traditional_descriptors) != set(WINDOW_NAMES)
    ):
        raise ValueError("online_expert_context_window_axis_invalid")
    windows = {}
    explicit_availability = {name: False for name in EXPLICIT_CONTEXT_FIELDS}
    maximum_abs_center_primary = 0.0
    maximum_abs_center_replication = 0.0
    for name in WINDOW_NAMES:
        v4_fields, v4_rows = _read_rows(v4_descriptors[name])
        _, v5_rows = _read_rows(v5_descriptors[name])
        _, selector_rows = _read_rows(traditional_descriptors[name])
        for context_name, aliases in EXPLICIT_CONTEXT_FIELDS.items():
            explicit_availability[context_name] = explicit_availability[context_name] or any(
                alias in v4_fields for alias in aliases
            )
        result = _audit_window(
            v4_rows,
            v5_rows,
            selector_rows,
            retrospective_context=context_windows[name],
        )
        windows[name] = result
        correlations = [
            abs(value)
            for horizon in result["loss_association_by_horizon"].values()
            for value in horizon["pearson_correlation_selector_minus_v5_squared_loss"].values()
            if value is not None
        ]
        maximum = max(correlations, default=0.0)
        if name == "center_hill_primary":
            maximum_abs_center_primary = maximum
        elif name == "center_hill_replication":
            maximum_abs_center_replication = maximum
    jpp_targets_degenerate = all(
        windows[name]["selector_minus_v5_squared_loss_target_variance"] == 0.0
        for name in ("j_percy_priest_primary", "j_percy_priest_replication")
    )
    explicit_context_absent = not any(explicit_availability.values())
    center_context_transfer = _context_transfer_diagnostic(
        windows["center_hill_primary"],
        windows["center_hill_replication"],
    )
    center_prediction_transfer = _feature_transfer_diagnostic(
        windows["center_hill_primary"],
        windows["center_hill_replication"],
        association_key="loss_association_by_horizon",
        features=PREDICTION_DERIVED_FEATURES,
    )
    jpp_context_transfer = _context_transfer_diagnostic(
        windows["j_percy_priest_primary"],
        windows["j_percy_priest_replication"],
    )
    return {
        "schema": SCHEMA,
        "status": "online_expert_context_sufficiency_audit_complete",
        "generated_at": _aware_datetime(
            generated_at if generated_at is not None else datetime.now(UTC)
        ).isoformat(),
        "implementation_artifacts": {
            "auditor": _artifact(AUDITOR_PATH, AUDITOR_PATH.read_bytes()),
        },
        "source_artifacts": {
            "j_percy_priest_v4_report": _artifact(jpp_v4_report_path, jpp_body),
            "center_hill_v4_report": _artifact(center_v4_report_path, center_body),
            "v5_report": _artifact(v5_report_path, v5_body),
            "traditional_selector_report": _artifact(
                traditional_report_path,
                traditional_body,
            ),
            "action_innovation_cross_system_report": _artifact(
                cross_system_report_path,
                cross_body,
            ),
            "retrospective_hydrologic_context": context_sources,
            "v4_predictions_by_window": {
                name: dict(value) for name, value in v4_descriptors.items()
            },
            "v5_predictions_by_window": {
                name: dict(value) for name, value in v5_descriptors.items()
            },
            "traditional_predictions_by_window": {
                name: dict(value) for name, value in traditional_descriptors.items()
            },
        },
        "feature_contract": {
            "prediction_derived_candidate_features": list(PREDICTION_DERIVED_FEATURES),
            "retrospective_hydrologic_features": list(RETROSPECTIVE_HYDROLOGIC_FEATURES),
            "candidate_features_use_target_outcome": False,
            "candidate_features_historically_available_within_replay": True,
            "retrospective_values_are_operational_forecasts": False,
            "source_publication_latency_audited": False,
            "operational_issue_time_vintages_verified": False,
            "target": "selector_squared_error_minus_v5_squared_error",
            "target_used_for_prediction": False,
            "feature_selection_or_gate_fitting_performed": False,
        },
        "explicit_hydrologic_context_availability": {
            "prediction_artifacts": explicit_availability,
            "separately_bound_historical_inputs": {
                "reservoir_release": True,
                "nwm_lateral_inflow": True,
                "precipitation": False,
                "soil_moisture_or_saturation": False,
            },
            "all_explicit_context_absent_from_prediction_artifacts": (explicit_context_absent),
            "historical_release_and_nwm_forcing_joined_to_issue_times": True,
            "operational_issue_time_vintages_verified": False,
        },
        "windows": windows,
        "retrospective_context_transfer_diagnostics": {
            "center_hill": {
                "retrospective_hydrologic_context": center_context_transfer,
                "prediction_derived_context": center_prediction_transfer,
            },
            "j_percy_priest": {
                "retrospective_hydrologic_context": jpp_context_transfer,
            },
        },
        "diagnostic_interpretation": {
            "maximum_absolute_candidate_feature_correlation_center_hill_primary": (
                maximum_abs_center_primary
            ),
            "maximum_absolute_candidate_feature_correlation_center_hill_replication": (
                maximum_abs_center_replication
            ),
            "j_percy_priest_comparison_target_degenerate": jpp_targets_degenerate,
            "explicit_context_absent_from_prediction_artifacts": (explicit_context_absent),
            "historical_release_and_nwm_forcing_available_separately": True,
            "historical_release_and_nwm_forcing_context_audited": True,
            "center_hill_context_same_sign_estimable_count": center_context_transfer[
                "same_sign_estimable_count"
            ],
            "center_hill_context_maximum_minimum_absolute_correlation": (
                center_context_transfer["maximum_minimum_absolute_correlation_across_windows"]
            ),
            "center_hill_prediction_derived_maximum_minimum_absolute_correlation": (
                center_prediction_transfer["maximum_minimum_absolute_correlation_across_windows"]
            ),
            "historical_context_strengthens_cross_window_signal_over_prediction_derived_features": (
                center_context_transfer["maximum_minimum_absolute_correlation_across_windows"]
                > center_prediction_transfer["maximum_minimum_absolute_correlation_across_windows"]
            ),
            "j_percy_priest_context_association_estimable": jpp_context_transfer[
                "any_association_estimable"
            ],
            "existing_prediction_artifacts_sufficient_for_context_gate": False,
            "context_gate_candidate_identified": False,
            "new_model_version_created": False,
            "prospective_primary_candidate_changed": False,
            "result_may_trigger_refit_on_these_windows": False,
        },
        "claim_boundary": {
            "context_sufficiency_posthoc_audited": True,
            "context_conditioned_gate_validated": False,
            "wwm_or_gwm_superiority_validated": False,
            "geospatial_kernel_validated": False,
            "runtime_default_enabled": False,
        },
    }


def _audit_window(
    v4_rows: list[dict[str, str]],
    v5_rows: list[dict[str, str]],
    selector_rows: list[dict[str, str]],
    *,
    retrospective_context: Mapping[str, Any],
) -> dict[str, Any]:
    v5_by_key = _index(v5_rows)
    selector_by_key = _index(selector_rows)
    if set(v5_by_key) != set(selector_by_key) or not set(v5_by_key).issubset(_index(v4_rows)):
        raise ValueError("online_expert_context_prediction_axis_invalid")
    associations = {}
    context_associations = {}
    total_target_values = []
    missing_physical_trajectory_by_horizon = {}
    for horizon in HORIZONS:
        samples = []
        context_samples = []
        horizon_v4_rows = [row for row in v4_rows if int(row["horizon_hours"]) == horizon]
        missing_physical_trajectory_by_horizon[str(horizon)] = sum(
            row.get("online_physical_trajectory_change_m3s", "") == "" for row in horizon_v4_rows
        )
        for row in horizon_v4_rows:
            key = _key(row)
            if key not in v5_by_key or row["observed_discharge_m3s"] == "":
                continue
            v5 = v5_by_key[key]
            selector = selector_by_key[key]
            observed = float(row["observed_discharge_m3s"])
            if (
                v5["observed_discharge_m3s"] != row["observed_discharge_m3s"]
                or selector["observed_discharge_m3s"] != row["observed_discharge_m3s"]
            ):
                raise ValueError("online_expert_context_observation_axis_invalid")
            level = float(row["causal_persistence_m3s"])
            latest_physical = float(row["physical_at_latest_observation_m3s"])
            raw = float(row["physical_open_loop_m3s"])
            v4_prediction = float(row["physical_online_residual_adaptation_m3s"])
            wwm = float(row["action_innovation_wwm_m3s"])
            scale = max(abs(level), 1.0)
            prediction_features = {
                "expert_delta_scaled": (wwm - v4_prediction) / scale,
                "absolute_expert_delta_scaled": abs(wwm - v4_prediction) / scale,
                "latest_physical_residual_scaled": (level - latest_physical) / scale,
                "raw_physical_target_change_scaled": (raw - latest_physical) / scale,
                "v4_target_change_scaled": (v4_prediction - level) / scale,
            }
            target = (float(selector["evidence_gated_follow_the_leader_m3s"]) - observed) ** 2 - (
                float(v5["physical_online_expert_blend_m3s"]) - observed
            ) ** 2
            context_features = _retrospective_hydrologic_features(
                retrospective_context,
                issue_time=cross._parse_time(row["issue_time_utc"]),
                scale=scale,
            )
            samples.append((prediction_features, target))
            context_samples.append((context_features, target))
            total_target_values.append(target)
        if not samples:
            raise ValueError("online_expert_context_complete_case_axis_invalid")
        associations[str(horizon)] = {
            "complete_case_count": len(samples),
            "pearson_correlation_selector_minus_v5_squared_loss": {
                feature: _pearson(
                    [sample[0][feature] for sample in samples],
                    [sample[1] for sample in samples],
                )
                for feature in PREDICTION_DERIVED_FEATURES
            },
            "mean_selector_minus_v5_squared_loss_m6s2": (
                sum(sample[1] for sample in samples) / len(samples)
            ),
        }
        context_associations[str(horizon)] = {
            "complete_case_count": len(context_samples),
            "pearson_correlation_selector_minus_v5_squared_loss": {
                feature: _pearson(
                    [sample[0][feature] for sample in context_samples],
                    [sample[1] for sample in context_samples],
                )
                for feature in RETROSPECTIVE_HYDROLOGIC_FEATURES
            },
            "mean_selector_minus_v5_squared_loss_m6s2": (
                sum(sample[1] for sample in context_samples) / len(context_samples)
            ),
        }
    return {
        "system_id": v4_rows[0]["system_id"],
        "loss_association_by_horizon": associations,
        "retrospective_hydrologic_context_loss_association_by_horizon": (context_associations),
        "selector_minus_v5_squared_loss_target_variance": _population_variance(total_target_values),
        "online_physical_trajectory_change_missing_count_by_horizon": (
            missing_physical_trajectory_by_horizon
        ),
        "future_target_observation_used_in_candidate_features": False,
        "retrospective_context_operational_vintages_verified": False,
        "retrospective_context_input_hour_count": retrospective_context["input_hour_count"],
        "retrospective_context_path_feature_count": retrospective_context["path_feature_count"],
    }


def _load_cross_system_report(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    claims = report.get("claim_boundary") or {}
    information = report.get("information_boundary") or {}
    if (
        report.get("schema") != cross.SCHEMA
        or report.get("status") != "zero_refit_cross_system_posthoc_failure_replicated"
        or not isinstance(report.get("source_artifacts"), Mapping)
        or not isinstance(report.get("outputs"), Mapping)
        or information.get("operational_issue_time_vintages_verified") is not False
        or claims.get("geospatial_kernel_validated") is not False
    ):
        raise ValueError("online_expert_context_cross_system_report_invalid")
    return body, report


def _load_retrospective_context_windows(
    cross_report: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Any]]:
    sources = cross_report["source_artifacts"]
    outputs = cross_report["outputs"]
    primary_descriptor = sources["input_report"]
    replication_descriptor = sources["replication_input_report"]
    primary_body = cross._read_verified(primary_descriptor)
    replication_body = cross._read_verified(replication_descriptor)
    primary = json.loads(primary_body)
    replication = json.loads(replication_body)
    _validate_context_input_report(primary, schema=cross.INPUT_SCHEMA)
    _validate_context_input_report(replication, schema=cross.REPLICATION_INPUT_SCHEMA)

    center_parameter_descriptor = sources["source_parameters"]
    jpp_parameter_descriptor = outputs["transferred_parameters"]
    center_parameter_body = cross._read_verified(center_parameter_descriptor)
    jpp_parameter_body = cross._read_verified(jpp_parameter_descriptor)
    center_parameters = action_innovation_transition_parameters_from_dict(
        json.loads(center_parameter_body)
    )
    jpp_parameters = action_innovation_transition_parameters_from_dict(
        json.loads(jpp_parameter_body)
    )
    parameters = {
        "center_hill": center_parameters,
        "j_percy_priest": jpp_parameters,
    }
    reports = {"primary": primary, "replication": replication}
    windows: dict[str, Mapping[str, Any]] = {}
    for system_name, parameter in parameters.items():
        if not parameter.support.network_id.startswith(system_name.replace("_", "-")):
            raise ValueError("online_expert_context_support_system_invalid")
        for role, report in reports.items():
            windows[f"{system_name}_{role}"] = _load_context_window(
                report["systems"][system_name],
                path_feature_ids=parameter.support.path_feature_ids,
                lag_hours=parameter.support.lag_hours,
                lag_weights=parameter.support.lag_weights,
            )
    return windows, {
        "primary_input_report": dict(primary_descriptor),
        "replication_input_report": dict(replication_descriptor),
        "center_hill_parameters": dict(center_parameter_descriptor),
        "j_percy_priest_transferred_parameters": dict(jpp_parameter_descriptor),
    }


def _validate_context_input_report(report: Mapping[str, Any], *, schema: str) -> None:
    claims = report.get("claim_boundary") or {}
    if (
        report.get("schema") != schema
        or report.get("status") != "pass_outcome_free_two_system_inputs_acquired"
        or (report.get("data_isolation") or {}).get("outcome_values_loaded") is not False
        or claims.get("geospatial_kernel_validated") is not False
        or set(report.get("systems", {})) != {"center_hill", "j_percy_priest"}
    ):
        raise ValueError("online_expert_context_input_report_invalid")


def _load_context_window(
    inputs: Mapping[str, Any],
    *,
    path_feature_ids: tuple[int, ...],
    lag_hours: tuple[int, ...],
    lag_weights: tuple[float, ...],
) -> Mapping[str, Any]:
    action_starts, valid_times, action_values = cross._parse_actions(
        cross._read_verified(inputs["action_values"])
    )
    arrays = inputs["decoded_arrays"]
    feature_ids = tuple(int(value) for value in cross._read_npy(arrays["feature_ids"]).tolist())
    forcing_times = tuple(
        cross._parse_time(str(value))
        for value in cross._read_npy(arrays["forcing_timestamps_utc"]).tolist()
    )
    q_lateral = np.asarray(cross._read_npy(arrays["q_lateral_m3s"]), dtype=float)
    try:
        path_indices = tuple(feature_ids.index(value) for value in path_feature_ids)
    except ValueError as exc:
        raise ValueError("online_expert_context_path_feature_missing") from exc
    if (
        action_starts != forcing_times
        or q_lateral.shape != (len(valid_times), len(feature_ids))
        or not np.isfinite(q_lateral).all()
        or bool((q_lateral < 0.0).any())
        or len(lag_hours) != len(lag_weights)
    ):
        raise ValueError("online_expert_context_hydrologic_axis_invalid")
    forcing_values = tuple(float(value) for value in q_lateral[:, path_indices].sum(axis=1))
    return {
        "action_by_valid_time": dict(zip(valid_times, action_values, strict=True)),
        "forcing_by_valid_time": dict(zip(valid_times, forcing_values, strict=True)),
        "lag_hours": lag_hours,
        "lag_weights": lag_weights,
        "input_hour_count": len(valid_times),
        "path_feature_count": len(path_feature_ids),
    }


def _retrospective_hydrologic_features(
    context: Mapping[str, Any],
    *,
    issue_time: datetime,
    scale: float,
) -> dict[str, float]:
    action = context["action_by_valid_time"]
    forcing = context["forcing_by_valid_time"]
    lag_hours = context["lag_hours"]
    lag_weights = context["lag_weights"]
    lag_times = tuple(issue_time - timedelta(hours=value) for value in lag_hours)
    previous_lag_times = tuple(value - timedelta(hours=1) for value in lag_times)
    required = (issue_time, *lag_times, *previous_lag_times)
    if issue_time not in forcing or any(value not in action for value in required):
        raise ValueError("online_expert_context_issue_time_uncovered")
    effective_action = sum(
        weight * action[valid_at] for valid_at, weight in zip(lag_times, lag_weights, strict=True)
    )
    previous_effective_action = sum(
        weight * action[valid_at]
        for valid_at, weight in zip(previous_lag_times, lag_weights, strict=True)
    )
    effective_change = effective_action - previous_effective_action
    return {
        "action_release_scaled": action[issue_time] / scale,
        "effective_action_change_scaled": effective_change / scale,
        "absolute_effective_action_change_scaled": abs(effective_change) / scale,
        "path_lateral_inflow_scaled": forcing[issue_time] / scale,
    }


def _context_transfer_diagnostic(
    primary: Mapping[str, Any],
    replication: Mapping[str, Any],
) -> dict[str, Any]:
    return _feature_transfer_diagnostic(
        primary,
        replication,
        association_key="retrospective_hydrologic_context_loss_association_by_horizon",
        features=RETROSPECTIVE_HYDROLOGIC_FEATURES,
    )


def _feature_transfer_diagnostic(
    primary: Mapping[str, Any],
    replication: Mapping[str, Any],
    *,
    association_key: str,
    features: tuple[str, ...],
) -> dict[str, Any]:
    primary_associations = primary[association_key]
    replication_associations = replication[association_key]
    comparisons = {}
    same_sign_count = 0
    estimable_count = 0
    minimum_absolute_values = []
    same_sign_minimum_absolute_values = []
    for horizon in HORIZONS:
        horizon_key = str(horizon)
        primary_values = primary_associations[horizon_key][
            "pearson_correlation_selector_minus_v5_squared_loss"
        ]
        replication_values = replication_associations[horizon_key][
            "pearson_correlation_selector_minus_v5_squared_loss"
        ]
        comparisons[horizon_key] = {}
        for feature in features:
            left = primary_values[feature]
            right = replication_values[feature]
            estimable = left is not None and right is not None
            same_sign = estimable and left * right > 0.0
            minimum_absolute = min(abs(left), abs(right)) if estimable else None
            estimable_count += int(estimable)
            same_sign_count += int(same_sign)
            if minimum_absolute is not None:
                minimum_absolute_values.append(minimum_absolute)
            if same_sign:
                same_sign_minimum_absolute_values.append(minimum_absolute)
            comparisons[horizon_key][feature] = {
                "primary_correlation": left,
                "replication_correlation": right,
                "both_estimable": estimable,
                "same_sign": same_sign,
                "minimum_absolute_correlation": minimum_absolute,
            }
    return {
        "by_horizon": comparisons,
        "association_comparison_count": len(HORIZONS) * len(features),
        "estimable_comparison_count": estimable_count,
        "same_sign_estimable_count": same_sign_count,
        "any_association_estimable": estimable_count > 0,
        "maximum_minimum_absolute_correlation_across_windows": max(
            same_sign_minimum_absolute_values,
            default=0.0,
        ),
        "maximum_minimum_absolute_correlation_across_windows_ignoring_sign": max(
            minimum_absolute_values,
            default=0.0,
        ),
    }


def _read_rows(descriptor: object) -> tuple[set[str], list[dict[str, str]]]:
    body = cross._read_verified(descriptor)
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    if reader.fieldnames is None:
        raise ValueError("online_expert_context_source_columns_invalid")
    rows = list(reader)
    required = {
        "system_id",
        "issue_time_utc",
        "target_support_end_utc",
        "horizon_hours",
        "observed_discharge_m3s",
    }
    if not rows or not required.issubset(reader.fieldnames):
        raise ValueError("online_expert_context_source_columns_invalid")
    return set(reader.fieldnames), rows


def _index(rows: list[dict[str, str]]) -> dict[tuple[str, str, str, str], dict[str, str]]:
    indexed = {_key(row): row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError("online_expert_context_duplicate_prediction")
    return indexed


def _key(row: Mapping[str, str]) -> tuple[str, str, str, str]:
    return (
        row["system_id"],
        row["issue_time_utc"],
        row["target_support_end_utc"],
        row["horizon_hours"],
    )


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or not left:
        raise ValueError("online_expert_context_correlation_axis_invalid")
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    left_sum = sum((value - left_mean) ** 2 for value in left)
    right_sum = sum((value - right_mean) ** 2 for value in right)
    denominator = math.sqrt(left_sum * right_sum)
    if denominator == 0.0:
        return None
    return (
        sum(
            (left_value - left_mean) * (right_value - right_mean)
            for left_value, right_value in zip(left, right, strict=True)
        )
        / denominator
    )


def _population_variance(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def _load_report(
    path: Path,
    *,
    schema: str,
    status: str,
) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    information = report.get("information_boundary") or {}
    claims = report.get("claim_boundary") or {}
    if (
        report.get("schema") != schema
        or report.get("status") != status
        or not isinstance(report.get("outputs"), Mapping)
        or information.get("evaluation_counts_as_fresh_validation") is not False
        or claims.get("geospatial_kernel_validated") is not False
    ):
        raise ValueError("online_expert_context_source_report_invalid")
    return body, report


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    try:
        display_path = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        display_path = str(path.resolve())
    return {
        "path": display_path,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("online_expert_context_generated_at_invalid")
    return value.astimezone(UTC)


def _json_body(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> None:
    args = parse_args()
    report = compile_online_expert_context_sufficiency_audit(
        jpp_v4_report_path=args.jpp_v4_report,
        center_v4_report_path=args.center_v4_report,
        v5_report_path=args.v5_report,
        traditional_report_path=args.traditional_report,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(_json_body(report))
    interpretation = report["diagnostic_interpretation"]
    print(f"status={report['status']}")
    print(
        f"context_gate_candidate_identified={interpretation['context_gate_candidate_identified']}"
    )


if __name__ == "__main__":
    main()
