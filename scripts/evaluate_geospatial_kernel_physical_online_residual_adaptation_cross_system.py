#!/usr/bin/env python3
"""Replay the fixed v4 online adapter on two historical Center Hill windows."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.physical_online_residual_adaptation import (
    PhysicalOnlineResidualAdaptationConfig,
    PhysicalOnlineResidualAdapter,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    from scripts import evaluate_geospatial_kernel_physical_action_innovation_transfer as action
    from scripts import evaluate_geospatial_kernel_physical_online_residual_adaptation as online
    from scripts import evaluate_geospatial_kernel_physical_residual_decay_transfer as decay
    from scripts import evaluate_geospatial_kernel_physical_routing_state_correction as baseline
else:
    import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    import evaluate_geospatial_kernel_physical_action_innovation_transfer as action
    import evaluate_geospatial_kernel_physical_online_residual_adaptation as online
    import evaluate_geospatial_kernel_physical_residual_decay_transfer as decay
    import evaluate_geospatial_kernel_physical_routing_state_correction as baseline


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
DEFAULT_SOURCE_REPORT = action.DEFAULT_REPORT
DEFAULT_PRIMARY_PHYSICAL_REPORT = decay.DEFAULT_SOURCE_PHYSICAL_REPORT
DEFAULT_REPLICATION_PHYSICAL_REPORT = decay.DEFAULT_REPLICATION_SOURCE_PHYSICAL_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_physical_online_residual_adaptation_center_hill_posthoc"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_physical_online_residual_adaptation_center_hill_posthoc_report.json"
)
SCHEMA = "gwm.geotransport.physical_online_residual_adaptation_cross_system_posthoc.v1"
SOURCE_SCHEMA = action.SCHEMA
SYSTEM_ID = action.SOURCE_SYSTEM_ID
HORIZONS = online.HORIZONS
OBSERVATION_LATENCY_HOURS = online.OBSERVATION_LATENCY_HOURS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-report",
        type=Path,
        default=DEFAULT_SOURCE_REPORT,
    )
    parser.add_argument(
        "--primary-physical-report",
        type=Path,
        default=DEFAULT_PRIMARY_PHYSICAL_REPORT,
    )
    parser.add_argument(
        "--replication-physical-report",
        type=Path,
        default=DEFAULT_REPLICATION_PHYSICAL_REPORT,
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_cross_system_online_residual_adaptation_posthoc(
    *,
    source_report_path: Path = DEFAULT_SOURCE_REPORT,
    primary_physical_report_path: Path = DEFAULT_PRIMARY_PHYSICAL_REPORT,
    replication_physical_report_path: Path = DEFAULT_REPLICATION_PHYSICAL_REPORT,
    primary_prediction_path: Path | None = None,
    replication_prediction_path: Path | None = None,
    generated_at: datetime | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Apply the J. Percy Priest-selected v4 mapping without re-selection."""

    primary_prediction_path = primary_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "center_hill_primary_predictions.csv"
    )
    replication_prediction_path = replication_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "center_hill_replication_predictions.csv"
    )
    source_report_body, source_report = _load_source_report(source_report_path)
    primary_wwm_descriptor = source_report["outputs"]["source_wwm_predictions"]
    replication_wwm_descriptor = source_report["outputs"]["replication_source_wwm_predictions"]
    primary_wwm_body = cross._read_verified(primary_wwm_descriptor)
    replication_wwm_body = cross._read_verified(replication_wwm_descriptor)

    primary_physical = decay._load_source_physical_rollout(
        path=primary_physical_report_path,
        expected_schema=baseline.PRIMARY_PHYSICAL_SCHEMA,
        expected_operator="BranchingManningNetworkTransportOperator",
        value_column="kernel_full_subnetwork_m3s",
        require_all_execution_gates=False,
    )
    replication_physical = decay._load_source_physical_rollout(
        path=replication_physical_report_path,
        expected_schema=baseline.REPLICATION_PHYSICAL_SCHEMA,
        expected_operator="BranchingFiniteVolumeKinematicWaveOperator",
        value_column="kinematic_wave_m3s",
        require_all_execution_gates=True,
    )
    _verify_source_physical_identity(
        source_report=source_report,
        primary_physical=primary_physical,
        replication_physical=replication_physical,
    )

    config = PhysicalOnlineResidualAdaptationConfig()
    primary_body, primary = _compile_window(
        source_body=primary_wwm_body,
        physical_body=primary_physical["prediction_body"],
        physical_value_column=primary_physical["value_column"],
        config=config,
    )
    replication_body, replication = _compile_window(
        source_body=replication_wwm_body,
        physical_body=replication_physical["prediction_body"],
        physical_value_column=replication_physical["value_column"],
        config=config,
    )
    results = (primary, replication)
    numerical_improvement_count = sum(
        values["online_minus_raw_physical_rmse_m3s"] < 0.0
        for result in results
        for values in result["comparison"]["per_horizon"].values()
    )
    hac_supported_improvement_count = sum(
        values["mean_improvement_exceeds_1_96_hac_standard_errors"]
        for result in results
        for values in result["paired_loss_diagnostic_by_horizon"].values()
    )
    beats_raw = all(
        result["comparison"]["online_beats_raw_physical_all_horizons"] for result in results
    )
    noninferior_raw = all(
        result["comparison"]["online_not_worse_than_raw_physical_all_horizons"]
        for result in results
    )
    unchanged_count = sum(
        values["online_minus_raw_physical_rmse_m3s"] == 0.0
        for result in results
        for values in result["comparison"]["per_horizon"].values()
    )
    regression_count = sum(
        values["online_minus_raw_physical_rmse_m3s"] > 0.0
        for result in results
        for values in result["comparison"]["per_horizon"].values()
    )
    outputs = {
        "primary_predictions": primary_body,
        "replication_predictions": replication_body,
    }
    report = {
        "schema": SCHEMA,
        "status": "fixed_v4_center_hill_cross_system_posthoc_complete",
        "generated_at": _aware_datetime(
            generated_at if generated_at is not None else datetime.now(UTC)
        ).isoformat(),
        "implementation_artifacts": {
            "cross_system_evaluator": _artifact(
                EVALUATOR_PATH,
                EVALUATOR_PATH.read_bytes(),
            ),
            "online_evaluator": _artifact(
                online.EVALUATOR_PATH,
                online.EVALUATOR_PATH.read_bytes(),
            ),
            "online_adapter": _artifact(
                online.CORE_OPERATOR_PATH,
                online.CORE_OPERATOR_PATH.read_bytes(),
            ),
        },
        "source_artifacts": {
            "physical_action_innovation_transfer_report": _artifact(
                source_report_path,
                source_report_body,
            ),
            "primary_wwm_predictions": dict(primary_wwm_descriptor),
            "replication_wwm_predictions": dict(replication_wwm_descriptor),
            "primary_physical_rollout_report": _artifact(
                primary_physical_report_path,
                primary_physical["report_body"],
            ),
            "primary_physical_predictions": dict(primary_physical["prediction_descriptor"]),
            "replication_physical_rollout_report": _artifact(
                replication_physical_report_path,
                replication_physical["report_body"],
            ),
            "replication_physical_predictions": dict(replication_physical["prediction_descriptor"]),
        },
        "outputs": {
            "primary_predictions": _artifact(
                primary_prediction_path,
                primary_body,
            ),
            "replication_predictions": _artifact(
                replication_prediction_path,
                replication_body,
            ),
        },
        "fixed_cross_system_contract": {
            **config.as_dict(),
            "system_id": SYSTEM_ID,
            "mapping_selected_from_j_percy_priest_historical_windows": True,
            "mapping_reselected_on_center_hill": False,
            "center_hill_outcomes_used_by_this_evaluator_to_select_mapping": False,
            "one_independent_online_state_per_center_hill_window": True,
            "online_weights_learned_only_from_matured_center_hill_outcomes": True,
            "parameter_state_transferred_between_systems": False,
            "observation_latency_hours": OBSERVATION_LATENCY_HOURS,
        },
        "primary_window": primary,
        "replication_window": replication,
        "diagnostic_interpretation": {
            "online_beats_raw_physical_all_horizons_in_both_windows": beats_raw,
            "online_not_worse_than_raw_physical_all_horizons_in_both_windows": (noninferior_raw),
            "numerical_rmse_improvement_window_horizon_count": (numerical_improvement_count),
            "unchanged_raw_physical_fallback_window_horizon_count": (unchanged_count),
            "numerical_rmse_regression_window_horizon_count": regression_count,
            "hac_supported_squared_error_improvement_window_horizon_count": (
                hac_supported_improvement_count
            ),
            "window_horizon_comparison_count": len(results) * len(HORIZONS),
            "fixed_phase_lead_algorithm_survives_center_hill_historical_stress_test": (beats_raw),
            "fixed_phase_lead_algorithm_no_regression_safety_gate_passed": (
                noninferior_raw and regression_count == 0
            ),
            "result_may_trigger_refit_on_these_windows": False,
        },
        "promotion_gate": {
            "must_beat_raw_physical_all_horizons_in_both_windows": True,
            "accuracy_requirement_passed": beats_raw,
            "fresh_prospective_design_required": True,
            "fresh_prospective_design_passed": False,
            "cross_system_online_adapter_promotion_gate_passed": False,
        },
        "information_boundary": {
            "center_hill_target_outcomes_exposed_before_this_evaluation": True,
            "future_target_observation_used_inside_forecast": False,
            "historical_realized_action_used_by_raw_physical_rollout": True,
            "retrospective_nwm_forcing_used_by_raw_physical_rollout": True,
            "physical_operator_form_differs_between_windows": True,
            "operational_issue_time_vintages_verified": False,
            "evaluation_counts_as_fresh_validation": False,
            "fresh_prospective_window_consumed": False,
        },
        "claim_boundary": {
            "fixed_v4_center_hill_posthoc_executed": True,
            "cross_system_algorithm_generalization_validated": False,
            "online_adaptation_admitted": False,
            "geospatial_kernel_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return outputs, report


def _compile_window(
    *,
    source_body: bytes,
    physical_body: bytes,
    physical_value_column: str,
    config: PhysicalOnlineResidualAdaptationConfig,
) -> tuple[bytes, dict[str, Any]]:
    source_rows = _source_rows(source_body)
    physical = baseline._physical_series(
        physical_body,
        value_column=physical_value_column,
    )
    rows_by_issue: dict[datetime, list[dict[str, str]]] = defaultdict(list)
    for source in source_rows:
        rows_by_issue[cross._parse_time(source["issue_time_utc"])].append(source)
    adapter = PhysicalOnlineResidualAdapter(config)
    pending: list[dict[str, Any]] = []
    rows: list[dict[str, object]] = []
    active_count = 0
    clipped_count = 0
    matured_update_count = 0
    for issue_time in sorted(rows_by_issue):
        still_pending = []
        for sample in pending:
            if sample["available_at"] <= issue_time:
                adapter.update(
                    sample_id=sample["sample_id"],
                    forecast_horizon_hours=sample["horizon"],
                    physical_trajectory_change_m3s=sample["physical_trajectory_change"],
                    physical_target_m3s=sample["physical_target"],
                    candidate_shadow_prediction_m3s=sample["shadow_prediction"],
                    candidate_evidence_gate_passed=sample["evidence_gate_passed"],
                    observed_target_m3s=sample["observed_target"],
                    target_observation_available_at=sample["available_at"],
                    update_time=issue_time,
                )
                matured_update_count += 1
            else:
                still_pending.append(sample)
        pending = still_pending
        issue_rows_by_horizon = {
            int(value["horizon_hours"]): value for value in rows_by_issue[issue_time]
        }
        for source in sorted(
            rows_by_issue[issue_time],
            key=lambda value: int(value["horizon_hours"]),
        ):
            horizon = int(source["horizon_hours"])
            target_time = cross._parse_time(source["target_support_end_utc"])
            latest_time = cross._parse_time(source["latest_observation_valid_at_utc"])
            if target_time not in physical or latest_time not in physical:
                raise ValueError("cross_system_online_physical_axis_invalid")
            physical_target = physical[target_time]
            physical_at_latest = physical[latest_time]
            predictor_horizon = dict(config.trajectory_predictor_horizon_pairs).get(horizon)
            predictor_source = issue_rows_by_horizon.get(predictor_horizon)
            predictor_time = (
                cross._parse_time(predictor_source["target_support_end_utc"])
                if predictor_source is not None
                else None
            )
            predictor_physical = (
                physical[predictor_time]
                if predictor_time is not None and predictor_time in physical
                else None
            )
            step = adapter.predict(
                forecast_horizon_hours=horizon,
                physical_at_latest_observation_m3s=physical_at_latest,
                predictor_physical_target_m3s=predictor_physical,
                physical_target_m3s=physical_target,
                issue_time=issue_time,
            )
            active_count += int(step.application_gate_passed)
            clipped_count += int(step.clipped)
            rows.append(
                {
                    "system_id": SYSTEM_ID,
                    "issue_time_utc": source["issue_time_utc"],
                    "target_support_end_utc": source["target_support_end_utc"],
                    "horizon_hours": horizon,
                    "observed_discharge_m3s": source["observed_discharge_m3s"],
                    "physical_open_loop_m3s": physical_target,
                    "physical_online_residual_adaptation_m3s": (step.corrected_prediction_m3s),
                    "action_innovation_wwm_m3s": source["action_innovation_candidate_m3s"],
                    "causal_persistence_m3s": source["causal_persistence_m3s"],
                    "physical_at_latest_observation_m3s": physical_at_latest,
                    "online_physical_trajectory_change_m3s": (step.physical_trajectory_change_m3s),
                    "online_predictor_forecast_horizon_hours": (
                        step.predictor_forecast_horizon_hours
                    ),
                    "online_predictor_physical_target_m3s": (step.predictor_physical_target_m3s),
                    "online_matured_sample_count": step.matured_sample_count,
                    "online_raw_weight": step.raw_weight,
                    "online_raw_bias_m3s": step.raw_bias_m3s,
                    "online_correction_mode": step.correction_mode,
                    "online_evidence_gate_passed": step.evidence_gate_passed,
                    "online_shadow_performance_gate_passed": (step.shadow_performance_gate_passed),
                    "online_application_gate_passed": (step.application_gate_passed),
                    "online_applied_weight": step.applied_weight,
                    "online_applied_bias_m3s": step.applied_bias_m3s,
                    "online_correction_clipped": step.clipped,
                    "target_observation_available_at_utc": online._iso(
                        target_time + timedelta(hours=OBSERVATION_LATENCY_HOURS)
                    ),
                    "future_target_observation_used_for_correction": False,
                    "mapping_reselected_on_center_hill": False,
                    "operational_vintages_verified": False,
                }
            )
            observed_text = source["observed_discharge_m3s"]
            predictor_available = (
                step.physical_trajectory_change_m3s is not None
                or horizon in config.bias_adaptive_forecast_horizons_hours
            )
            if observed_text != "" and predictor_available:
                observed = float(observed_text)
                if not math.isfinite(observed):
                    raise ValueError("cross_system_online_observation_invalid")
                available_at = target_time + timedelta(hours=OBSERVATION_LATENCY_HOURS)
                pending.append(
                    {
                        "sample_id": (
                            f"{source['issue_time_utc']}:{horizon}:"
                            f"{source['target_support_end_utc']}"
                        ),
                        "horizon": horizon,
                        "physical_trajectory_change": (step.physical_trajectory_change_m3s or 0.0),
                        "physical_target": physical_target,
                        "shadow_prediction": step.shadow_prediction_m3s,
                        "evidence_gate_passed": step.evidence_gate_passed,
                        "observed_target": observed,
                        "available_at": available_at,
                    }
                )
    columns = {
        "physical_open_loop": "physical_open_loop_m3s",
        "physical_online_residual_adaptation": ("physical_online_residual_adaptation_m3s"),
        "action_innovation_wwm": "action_innovation_wwm_m3s",
        "causal_persistence": "causal_persistence_m3s",
    }
    metrics, scoring = candidate._score(rows, columns)
    return cross._encode_rows(rows), {
        "window": {
            "first_issue_time_utc": online._iso(min(rows_by_issue)),
            "last_issue_time_utc": online._iso(max(rows_by_issue)),
            "horizons_hours": list(HORIZONS),
            "online_state_reset_at_window_start": True,
        },
        "metrics_by_horizon": metrics,
        "comparison": _comparison(metrics),
        "paired_loss_diagnostic_by_horizon": online._paired_loss_diagnostics(rows),
        "scoring": scoring,
        "execution": {
            "prediction_row_count": len(rows),
            "forecast_issue_count": len(rows_by_issue),
            "matured_outcome_update_count": matured_update_count,
            "evidence_activated_prediction_count": active_count,
            "raw_physical_fallback_prediction_count": len(rows) - active_count,
            "corrected_prediction_clipped_count": clipped_count,
            "final_matured_sample_count_by_horizon": {
                str(key): value for key, value in adapter.sample_count_by_horizon().items()
            },
            "future_target_observation_used_before_availability": False,
            "mapping_reselected_on_center_hill": False,
        },
    }


def _source_rows(body: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    required = {
        "system_id",
        "issue_time_utc",
        "target_support_end_utc",
        "horizon_hours",
        "observed_discharge_m3s",
        "action_innovation_candidate_m3s",
        "causal_persistence_m3s",
        "latest_observation_valid_at_utc",
        "latest_observation_available_at_utc",
        "future_outcome_observation_used",
        "operational_vintages_verified",
    }
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("cross_system_online_source_columns_invalid")
    rows = list(reader)
    if not rows:
        raise ValueError("cross_system_online_source_axis_invalid")
    for row in rows:
        issue_time = cross._parse_time(row["issue_time_utc"])
        target_time = cross._parse_time(row["target_support_end_utc"])
        horizon = int(row["horizon_hours"])
        latest_valid = cross._parse_time(row["latest_observation_valid_at_utc"])
        latest_available = cross._parse_time(row["latest_observation_available_at_utc"])
        if (
            row["system_id"] != SYSTEM_ID
            or horizon not in HORIZONS
            or target_time != issue_time + timedelta(hours=horizon)
            or latest_valid != issue_time - timedelta(hours=1)
            or latest_available != issue_time
            or row["future_outcome_observation_used"] != "False"
            or row["operational_vintages_verified"] != "False"
        ):
            raise ValueError("cross_system_online_source_axis_invalid")
    return rows


def _comparison(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> dict[str, Any]:
    comparators = {
        "raw_physical": "physical_open_loop",
        "wwm": "action_innovation_wwm",
        "persistence": "causal_persistence",
    }
    per_horizon = {}
    for horizon in HORIZONS:
        values = metrics[str(horizon)]
        online_rmse = values["physical_online_residual_adaptation"]["rmse_m3s"]
        per_horizon[str(horizon)] = {
            f"online_minus_{name}_rmse_m3s": (online_rmse - values[column]["rmse_m3s"])
            for name, column in comparators.items()
        }
    result: dict[str, Any] = {"per_horizon": per_horizon}
    for name in comparators:
        deltas = [
            per_horizon[str(horizon)][f"online_minus_{name}_rmse_m3s"] for horizon in HORIZONS
        ]
        result[f"online_beats_{name}_all_horizons"] = all(delta < 0.0 for delta in deltas)
        result[f"online_not_worse_than_{name}_all_horizons"] = all(delta <= 0.0 for delta in deltas)
        result[f"online_beats_{name}_horizons_hours"] = [
            horizon for horizon, delta in zip(HORIZONS, deltas, strict=True) if delta < 0.0
        ]
    return result


def _load_source_report(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    outputs = report.get("outputs") or {}
    claims = report.get("claim_boundary") or {}
    information = report.get("information_boundary") or {}
    if (
        report.get("schema") != SOURCE_SCHEMA
        or report.get("status")
        != "source_fitted_physical_action_innovation_transfer_posthoc_complete"
        or claims.get("geospatial_kernel_validated") is not False
        or information.get("evaluation_counts_as_fresh_validation") is not False
        or not {
            "source_wwm_predictions",
            "replication_source_wwm_predictions",
        }.issubset(outputs)
    ):
        raise ValueError("cross_system_online_source_report_invalid")
    return body, report


def _verify_source_physical_identity(
    *,
    source_report: Mapping[str, Any],
    primary_physical: Mapping[str, Any],
    replication_physical: Mapping[str, Any],
) -> None:
    source_artifacts = source_report.get("source_artifacts") or {}
    expected = (
        source_artifacts.get("source_physical_rollout_report") or {},
        source_artifacts.get("replication_source_physical_rollout_report") or {},
    )
    actual = (
        _artifact(
            DEFAULT_PRIMARY_PHYSICAL_REPORT,
            primary_physical["report_body"],
        ),
        _artifact(
            DEFAULT_REPLICATION_PHYSICAL_REPORT,
            replication_physical["report_body"],
        ),
    )
    if any(
        cross._descriptor_identity(left) != cross._descriptor_identity(right)
        for left, right in zip(expected, actual, strict=True)
    ):
        raise ValueError("cross_system_online_physical_identity_invalid")


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
        raise ValueError("cross_system_online_generated_at_invalid")
    return value.astimezone(UTC)


def _json_body(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> None:
    args = parse_args()
    paths = {
        "primary_predictions": (args.output_root / "center_hill_primary_predictions.csv"),
        "replication_predictions": (args.output_root / "center_hill_replication_predictions.csv"),
    }
    bodies, report = compile_cross_system_online_residual_adaptation_posthoc(
        source_report_path=args.source_report,
        primary_physical_report_path=args.primary_physical_report,
        replication_physical_report_path=args.replication_physical_report,
        primary_prediction_path=paths["primary_predictions"],
        replication_prediction_path=paths["replication_predictions"],
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        paths[name].write_bytes(body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    for window_name in ("primary_window", "replication_window"):
        for horizon in HORIZONS:
            values = report[window_name]["comparison"]["per_horizon"][str(horizon)]
            print(
                f"window={window_name} horizon={horizon}h "
                f"online_minus_raw_rmse="
                f"{values['online_minus_raw_physical_rmse_m3s']:.6f}"
            )


if __name__ == "__main__":
    main()
