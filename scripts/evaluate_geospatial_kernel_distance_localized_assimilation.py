#!/usr/bin/env python3
"""Test whether deterministic distance localization rescues graph assimilation."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__:
    from scripts.audit_geospatial_kernel_conservative_twin_action_response import (
        _artifact,
    )
    from scripts.evaluate_geospatial_kernel_issue_state_assimilation import (
        CALIBRATION_END_ISSUE_INDEX,
        DEFAULT_INPUT_REPORT,
        DEFAULT_OUTCOME_REPORT,
        DEFAULT_PROTOCOL,
        DEFAULT_ROLLOUT_REPORT,
        GRAPH_PATH,
        HORIZONS_HOURS,
        ISSUE_INDICES,
        LINEAR_DISTANCE_MODE,
        QUADRATIC_DISTANCE_MODE,
        REPO_ROOT,
        SYSTEM_IDS,
        _aggregate_mode_metrics,
        _aware,
        _encode_rows,
        _evaluate_system,
        _load_json,
        _select_mode,
        _validate_issue_indices,
        _validate_lineage,
        _validation_comparison,
    )
    from scripts.run_geotransport_v2_blind_validation_outcome_free import (
        _read_verified,
    )
else:
    from audit_geospatial_kernel_conservative_twin_action_response import _artifact
    from evaluate_geospatial_kernel_issue_state_assimilation import (
        CALIBRATION_END_ISSUE_INDEX,
        DEFAULT_INPUT_REPORT,
        DEFAULT_OUTCOME_REPORT,
        DEFAULT_PROTOCOL,
        DEFAULT_ROLLOUT_REPORT,
        GRAPH_PATH,
        HORIZONS_HOURS,
        ISSUE_INDICES,
        LINEAR_DISTANCE_MODE,
        QUADRATIC_DISTANCE_MODE,
        REPO_ROOT,
        SYSTEM_IDS,
        _aggregate_mode_metrics,
        _aware,
        _encode_rows,
        _evaluate_system,
        _load_json,
        _select_mode,
        _validate_issue_indices,
        _validate_lineage,
        _validation_comparison,
    )
    from run_geotransport_v2_blind_validation_outcome_free import _read_verified

MODES = (
    "nominal",
    "outlet_only_observation_update",
    LINEAR_DISTANCE_MODE,
    QUADRATIC_DISTANCE_MODE,
)
LOCALIZED_MODES = (LINEAR_DISTANCE_MODE, QUADRATIC_DISTANCE_MODE)
DEFAULT_PARENT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_issue_state_assimilation_posthoc_report.json"
)
DEFAULT_OUTPUT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_distance_localized_assimilation_posthoc/predictions.csv"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_distance_localized_assimilation_posthoc_report.json"
)
PARENT_SCHEMA = "gwm.geotransport.issue_state_assimilation_posthoc.v1"
SCHEMA = "gwm.geotransport.distance_localized_assimilation_posthoc.v1"
HORIZON_ROLLOUT_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/horizon_assimilation_rollout.py"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--input-report", type=Path, default=DEFAULT_INPUT_REPORT)
    parser.add_argument("--rollout-report", type=Path, default=DEFAULT_ROLLOUT_REPORT)
    parser.add_argument("--outcome-report", type=Path, default=DEFAULT_OUTCOME_REPORT)
    parser.add_argument("--parent-report", type=Path, default=DEFAULT_PARENT_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_distance_localized_assimilation_posthoc(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    input_report_path: Path = DEFAULT_INPUT_REPORT,
    rollout_report_path: Path = DEFAULT_ROLLOUT_REPORT,
    outcome_report_path: Path = DEFAULT_OUTCOME_REPORT,
    parent_report_path: Path = DEFAULT_PARENT_REPORT,
    output_path: Path = DEFAULT_OUTPUT,
    issue_indices: tuple[int, ...] = ISSUE_INDICES,
    calibration_end_issue_index: int = CALIBRATION_END_ISSUE_INDEX,
    generated_at: datetime | None = None,
) -> tuple[bytes, dict[str, Any]]:
    protocol_body, protocol = _load_json(protocol_path)
    input_body, inputs = _load_json(input_report_path)
    rollout_body, rollout = _load_json(rollout_report_path)
    outcome_body, outcomes = _load_json(outcome_report_path)
    parent_body, parent = _load_json(parent_report_path)
    _validate_lineage(
        protocol_body=protocol_body,
        protocol=protocol,
        input_body=input_body,
        inputs=inputs,
        rollout_body=rollout_body,
        rollout=rollout,
        outcome_body=outcome_body,
        outcomes=outcomes,
    )
    _validate_parent(parent)
    selected_issues = _validate_issue_indices(
        issue_indices,
        calibration_end_issue_index=calibration_end_issue_index,
    )

    rows: list[dict[str, object]] = []
    system_reports: dict[str, dict[str, Any]] = {}
    for system_id in SYSTEM_IDS:
        system_rows, system_report = _evaluate_system(
            system_id=system_id,
            lock=protocol["systems"][system_id],
            inputs=inputs["systems"][system_id],
            outcome_metadata=outcomes["systems"][system_id],
            sealed_prediction_body=_read_verified(
                rollout["systems"][system_id]["prediction_artifact"]
            ),
            outcome_values_body=_read_verified(outcomes["systems"][system_id]["outcome_values"]),
            issue_indices=selected_issues,
            calibration_end_issue_index=calibration_end_issue_index,
            modes=MODES,
        )
        rows.extend(system_rows)
        system_reports[system_id] = system_report

    calibration = _aggregate_mode_metrics(
        system_reports,
        split_key="calibration_metrics",
        modes=MODES,
    )
    selected_mode = _select_mode(calibration, modes=MODES)
    validation = _aggregate_mode_metrics(
        system_reports,
        split_key="validation_metrics",
        modes=MODES,
    )
    for system in system_reports.values():
        system["selected_mode_from_joint_calibration"] = selected_mode
        system["validation_comparison"] = _validation_comparison(
            system["validation_metrics"],
            selected_mode=selected_mode,
        )
        system["localization_validation_comparison"] = _mode_comparison(
            system["validation_metrics"],
            baseline_mode="outlet_only_observation_update",
        )

    selected_is_localized = selected_mode in LOCALIZED_MODES
    selected_beats_outlet = all(
        system["localization_validation_comparison"]["modes"][selected_mode][
            "beats_baseline_all_horizons"
        ]
        for system in system_reports.values()
    )
    selected_beats_nominal = all(
        system["validation_comparison"]["selected_mode_beats_nominal_all_horizons"]
        for system in system_reports.values()
    )
    selected_beats_persistence = all(
        system["validation_comparison"]["selected_mode_beats_persistence_all_horizons"]
        for system in system_reports.values()
    )
    mass_gate = all(
        system["execution_gates"]["all_physical_mass_balances_passed"]
        for system in system_reports.values()
    )
    branch_gate = all(
        system["execution_gates"]["mainstem_update_preserved_all_branch_states"]
        for system in system_reports.values()
    )
    historical_support = (
        selected_is_localized
        and selected_beats_outlet
        and selected_beats_nominal
        and selected_beats_persistence
        and mass_gate
        and branch_gate
    )
    csv_body = _encode_rows(rows)
    now = generated_at or datetime.now(UTC)
    if not _aware(now):
        raise ValueError("distance_localized_assimilation_generated_at_must_be_aware")
    report = {
        "schema": SCHEMA,
        "status": "historical_distance_localized_assimilation_complete_not_promoted",
        "generated_at": now.astimezone(UTC).isoformat(),
        "design": {
            "systems": list(SYSTEM_IDS),
            "modes": list(MODES),
            "localized_modes": list(LOCALIZED_MODES),
            "issue_indices": list(selected_issues),
            "calibration_issue_indices": [
                value for value in selected_issues if value < calibration_end_issue_index
            ],
            "validation_issue_indices": [
                value for value in selected_issues if value >= calibration_end_issue_index
            ],
            "calibration_end_issue_index_exclusive": calibration_end_issue_index,
            "horizons_hours": list(HORIZONS_HOURS),
            "selection_scope": "joint_two_system_calibration_split_only",
            "selection_objective": (
                "minimum_equal_system_equal_horizon_mean_MSE_on_calibration_split"
            ),
            "selection_tie_break": "nominal_then_outlet_then_linear_then_quadratic",
            "linear_gain": ("1 - downstream_distance_to_outlet / maximum_mainstem_distance"),
            "quadratic_gain": "linear_gain_squared",
            "outlet_local_update_separate": True,
            "action_entry_spatial_gain": 0.0,
            "outlet_graph_gain": 0.0,
            "branch_spatial_gain": 0.0,
            "outcome_fitted_numeric_localization_parameter_count": 0,
            "localization_family_selected_with_calibration_outcomes": True,
            "future_archived_actions_used": True,
            "future_retrospective_nwm_forcing_used": True,
        },
        "parent_evidence": {
            "issue_state_assimilation_report": _artifact(
                parent_report_path,
                parent_body,
            ),
            "parent_selected_mode": parent["selected_mode_from_joint_calibration"],
            "parent_historical_support_gate_passed": parent["aggregate_gates"][
                "historical_assimilation_support_gate_passed"
            ],
        },
        "source_artifacts": {
            "blind_validation_protocol": _artifact(protocol_path, protocol_body),
            "blind_validation_input_report": _artifact(input_report_path, input_body),
            "sealed_rollout_report": _artifact(rollout_report_path, rollout_body),
            "outcome_report": _artifact(outcome_report_path, outcome_body),
        },
        "implementation_artifacts": {
            "shared_issue_state_evaluator": _artifact(
                REPO_ROOT / "scripts/evaluate_geospatial_kernel_issue_state_assimilation.py",
                (
                    REPO_ROOT / "scripts/evaluate_geospatial_kernel_issue_state_assimilation.py"
                ).read_bytes(),
            ),
            "graph_state_update_contract": _artifact(
                GRAPH_PATH,
                GRAPH_PATH.read_bytes(),
            ),
            "horizon_assimilation_rollout_core": _artifact(
                HORIZON_ROLLOUT_PATH,
                HORIZON_ROLLOUT_PATH.read_bytes(),
            ),
            "evaluator": _artifact(Path(__file__), Path(__file__).read_bytes()),
        },
        "systems": system_reports,
        "joint_calibration_metrics": calibration,
        "selected_mode_from_joint_calibration": selected_mode,
        "joint_validation_metrics": validation,
        "joint_validation_mode_comparison": _aggregate_comparison(
            validation,
            baseline_mode="outlet_only_observation_update",
        ),
        "aggregate_gates": {
            "both_systems_nominal_replay_matches_sealed_predictions": all(
                system["execution_gates"]["nominal_replay_matches_sealed_predictions"]
                for system in system_reports.values()
            ),
            "both_systems_all_analysis_ledgers_passed": all(
                system["execution_gates"]["all_analysis_ledgers_passed"]
                for system in system_reports.values()
            ),
            "both_systems_all_physical_mass_balances_passed": mass_gate,
            "both_systems_localized_updates_preserved_all_branch_states": branch_gate,
            "selected_mode_is_distance_localized": selected_is_localized,
            "selected_mode_beats_outlet_all_validation_horizons_both_systems": (
                selected_beats_outlet
            ),
            "selected_mode_beats_nominal_all_validation_horizons_both_systems": (
                selected_beats_nominal
            ),
            "selected_mode_beats_persistence_all_validation_horizons_both_systems": (
                selected_beats_persistence
            ),
            "historical_localization_support_gate_passed": historical_support,
            "fresh_prospective_validation_passed": False,
            "candidate_promotion_gate_passed": False,
        },
        "outputs": {"predictions": _artifact(output_path, csv_body)},
        "information_boundary": {
            "future_target_used_for_issue_state_update": False,
            "calibration_targets_used_for_family_selection": True,
            "validation_targets_used_for_family_selection": False,
            "historical_outcomes_were_exposed_before_experiment_design": True,
            "actual_operational_usgs_latency_verified": False,
            "negative_discharge_used_in_forward_manning_inversion": False,
            "operational_action_schedule_vintage_verified": False,
            "nwm_forecast_forcing_used": False,
            "nwm_v3_retrospective_forcing_used": True,
        },
        "claim_boundary": {
            "distance_localization_candidate_evaluated": True,
            "distance_localization_candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "prospective_v5_changed": False,
            "candidate_promoted": False,
            "runtime_default_enabled": False,
        },
    }
    return csv_body, report


def _validate_parent(parent: Mapping[str, Any]) -> None:
    if (
        parent.get("schema") != PARENT_SCHEMA
        or parent.get("status") != "historical_issue_state_assimilation_complete_not_promoted"
        or parent.get("selected_mode_from_joint_calibration") != "outlet_only_observation_update"
        or parent.get("aggregate_gates", {}).get("candidate_promotion_gate_passed") is not False
        or parent.get("claim_boundary", {}).get("prospective_v5_changed") is not False
    ):
        raise ValueError("distance_localized_assimilation_parent_invalid")
    descriptors = list(parent.get("implementation_artifacts", {}).values()) + list(
        parent.get("outputs", {}).values()
    )
    if not descriptors:
        raise ValueError("distance_localized_assimilation_parent_artifacts_missing")
    for descriptor in descriptors:
        path = REPO_ROOT / descriptor["path"]
        if (
            not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest() != descriptor["sha256"]
        ):
            raise ValueError("distance_localized_assimilation_parent_hash_mismatch")


def _mode_comparison(
    metrics: Mapping[str, Any],
    *,
    baseline_mode: str,
) -> dict[str, Any]:
    baseline = metrics["modes"][baseline_mode]
    result: dict[str, Any] = {"baseline_mode": baseline_mode, "modes": {}}
    for mode in MODES:
        candidate = metrics["modes"][mode]
        horizon_wins: list[int] = []
        per_horizon: dict[str, Any] = {}
        for horizon in HORIZONS_HOURS:
            candidate_rmse = float(
                candidate["metrics_by_horizon"][str(horizon)]["prediction"]["rmse_m3s"]
            )
            baseline_rmse = float(
                baseline["metrics_by_horizon"][str(horizon)]["prediction"]["rmse_m3s"]
            )
            if candidate_rmse < baseline_rmse:
                horizon_wins.append(horizon)
            per_horizon[str(horizon)] = {
                "candidate_rmse_m3s": candidate_rmse,
                "baseline_rmse_m3s": baseline_rmse,
                "candidate_minus_baseline_rmse_m3s": candidate_rmse - baseline_rmse,
            }
        candidate_mse = float(candidate["equal_horizon_mean_mse_m6s2"])
        baseline_mse = float(baseline["equal_horizon_mean_mse_m6s2"])
        result["modes"][mode] = {
            "per_horizon": per_horizon,
            "beats_baseline_horizons_hours": horizon_wins,
            "beats_baseline_all_horizons": len(horizon_wins) == len(HORIZONS_HOURS),
            "equal_horizon_mean_mse_ratio_to_baseline": (candidate_mse / baseline_mse),
        }
    return result


def _aggregate_comparison(
    metrics: Mapping[str, Any],
    *,
    baseline_mode: str,
) -> dict[str, Any]:
    baseline = float(metrics["modes"][baseline_mode]["equal_system_equal_horizon_mean_mse_m6s2"])
    return {
        "baseline_mode": baseline_mode,
        "modes": {
            mode: {
                "equal_system_equal_horizon_mean_mse_ratio_to_baseline": float(
                    metrics["modes"][mode]["equal_system_equal_horizon_mean_mse_m6s2"]
                )
                / baseline
            }
            for mode in MODES
        },
    }


def main() -> int:
    args = parse_args()
    body, report = compile_distance_localized_assimilation_posthoc(
        protocol_path=args.protocol,
        input_report_path=args.input_report,
        rollout_report_path=args.rollout_report,
        outcome_report_path=args.outcome_report,
        parent_report_path=args.parent_report,
        output_path=args.output,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(body)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    print(f"selected_mode={report['selected_mode_from_joint_calibration']}")
    for mode in LOCALIZED_MODES:
        ratio = report["joint_validation_mode_comparison"]["modes"][mode][
            "equal_system_equal_horizon_mean_mse_ratio_to_baseline"
        ]
        print(f"{mode}_validation_mse_ratio_to_outlet={ratio}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
