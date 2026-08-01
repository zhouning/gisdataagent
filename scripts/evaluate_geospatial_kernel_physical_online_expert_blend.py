#!/usr/bin/env python3
"""Evaluate a causal physical-first online expert blend across four windows."""

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

from data_agent.uwm.geospatial_kernel_v2.physical_online_expert_blend import (
    PhysicalOnlineExpertBlendConfig,
    PhysicalOnlineExpertBlender,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    from scripts import evaluate_geospatial_kernel_physical_online_residual_adaptation as online
    from scripts import (
        evaluate_geospatial_kernel_physical_online_residual_adaptation_cross_system as center,
    )
else:
    import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    import evaluate_geospatial_kernel_physical_online_residual_adaptation as online
    import evaluate_geospatial_kernel_physical_online_residual_adaptation_cross_system as center


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
CORE_OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/physical_online_expert_blend.py"
)
DEFAULT_JPP_REPORT = online.DEFAULT_REPORT
DEFAULT_CENTER_HILL_REPORT = center.DEFAULT_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/geospatial_kernel_physical_online_expert_blend_posthoc"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_physical_online_expert_blend_posthoc_report.json"
)
SCHEMA = "gwm.geotransport.physical_online_expert_blend_posthoc.v1"
HORIZONS = online.HORIZONS
OBSERVATION_LATENCY_HOURS = online.OBSERVATION_LATENCY_HOURS
WINDOW_NAMES = (
    "j_percy_priest_primary",
    "j_percy_priest_replication",
    "center_hill_primary",
    "center_hill_replication",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--jpp-report",
        type=Path,
        default=DEFAULT_JPP_REPORT,
    )
    parser.add_argument(
        "--center-hill-report",
        type=Path,
        default=DEFAULT_CENTER_HILL_REPORT,
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_physical_online_expert_blend_posthoc(
    *,
    jpp_report_path: Path = DEFAULT_JPP_REPORT,
    center_hill_report_path: Path = DEFAULT_CENTER_HILL_REPORT,
    prediction_paths: Mapping[str, Path] | None = None,
    generated_at: datetime | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Replay one fixed causal blend with independent state in every window."""

    prediction_paths = dict(prediction_paths or _default_prediction_paths())
    if set(prediction_paths) != set(WINDOW_NAMES):
        raise ValueError("physical_online_expert_blend_output_paths_invalid")
    jpp_body, jpp_report = _load_source_report(
        path=jpp_report_path,
        expected_schema=online.SCHEMA,
        expected_status="causal_online_residual_adaptation_posthoc_complete",
        execution_claim="physical_online_residual_adaptation_posthoc_executed",
    )
    center_body, center_report = _load_source_report(
        path=center_hill_report_path,
        expected_schema=center.SCHEMA,
        expected_status="fixed_v4_center_hill_cross_system_posthoc_complete",
        execution_claim="fixed_v4_center_hill_posthoc_executed",
    )
    descriptors = {
        "j_percy_priest_primary": jpp_report["outputs"]["primary_predictions"],
        "j_percy_priest_replication": jpp_report["outputs"]["replication_predictions"],
        "center_hill_primary": center_report["outputs"]["primary_predictions"],
        "center_hill_replication": center_report["outputs"]["replication_predictions"],
    }
    config = PhysicalOnlineExpertBlendConfig()
    outputs: dict[str, bytes] = {}
    windows: dict[str, dict[str, Any]] = {}
    for name in WINDOW_NAMES:
        source_body = cross._read_verified(descriptors[name])
        output_body, result = _compile_window(
            source_body=source_body,
            config=config,
        )
        outputs[name] = output_body
        windows[name] = result

    numerical_vs_raw = _count_deltas(windows, comparator="raw_physical", sign=-1)
    numerical_vs_v4 = _count_deltas(windows, comparator="v4", sign=-1)
    regression_vs_raw = _count_deltas(windows, comparator="raw_physical", sign=1)
    regression_vs_v4 = _count_deltas(windows, comparator="v4", sign=1)
    beats_raw = all(
        result["comparison"]["blend_beats_raw_physical_all_horizons"] for result in windows.values()
    )
    noninferior_v4 = all(
        result["comparison"]["blend_not_worse_than_v4_all_horizons"] for result in windows.values()
    )
    hac_vs_raw = sum(
        diagnostic["mean_improvement_exceeds_1_96_hac_standard_errors"]
        for result in windows.values()
        for diagnostic in result["paired_loss_diagnostic_vs_raw_physical_by_horizon"].values()
    )
    hac_vs_v4 = sum(
        diagnostic["mean_improvement_exceeds_1_96_hac_standard_errors"]
        for result in windows.values()
        for diagnostic in result["paired_loss_diagnostic_vs_v4_by_horizon"].values()
    )
    report = {
        "schema": SCHEMA,
        "status": "physical_first_online_expert_blend_posthoc_complete",
        "generated_at": _aware_datetime(
            generated_at if generated_at is not None else datetime.now(UTC)
        ).isoformat(),
        "implementation_artifacts": {
            "online_expert_blender": _artifact(
                CORE_OPERATOR_PATH,
                CORE_OPERATOR_PATH.read_bytes(),
            ),
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        },
        "source_artifacts": {
            "j_percy_priest_v4_report": _artifact(
                jpp_report_path,
                jpp_body,
            ),
            "center_hill_v4_report": _artifact(
                center_hill_report_path,
                center_body,
            ),
            "source_predictions_by_window": {
                name: dict(descriptor) for name, descriptor in descriptors.items()
            },
        },
        "outputs": {
            name: _artifact(prediction_paths[name], outputs[name]) for name in WINDOW_NAMES
        },
        "fixed_online_contract": {
            **config.as_dict(),
            "observation_latency_hours": OBSERVATION_LATENCY_HOURS,
            "one_independent_online_state_per_window": True,
            "parameter_state_transferred_between_systems_or_windows": False,
            "future_target_rows_queued_outside_model_until_available": True,
            "baseline_and_alternative_predictions_are_already_causal": True,
        },
        "windows": windows,
        "diagnostic_interpretation": {
            "blend_beats_raw_physical_all_horizons_in_all_four_windows": (beats_raw),
            "blend_not_worse_than_v4_all_horizons_in_all_four_windows": (noninferior_v4),
            "numerical_rmse_improvement_vs_raw_physical_window_horizon_count": (numerical_vs_raw),
            "numerical_rmse_regression_vs_raw_physical_window_horizon_count": (regression_vs_raw),
            "numerical_rmse_improvement_vs_v4_window_horizon_count": (numerical_vs_v4),
            "numerical_rmse_regression_vs_v4_window_horizon_count": (regression_vs_v4),
            "hac_supported_squared_error_improvement_vs_raw_physical_count": (hac_vs_raw),
            "hac_supported_squared_error_improvement_vs_v4_count": hac_vs_v4,
            "window_horizon_comparison_count": len(WINDOW_NAMES) * len(HORIZONS),
            "online_expert_blend_accuracy_gate_passed_posthoc": beats_raw and noninferior_v4,
            "result_may_trigger_refit_on_these_windows": False,
        },
        "promotion_gate": {
            "must_beat_raw_physical_all_horizons_in_all_four_windows": True,
            "must_not_regress_v4_any_horizon": True,
            "accuracy_requirement_passed": beats_raw and noninferior_v4,
            "fresh_prospective_design_required": True,
            "fresh_prospective_design_passed": False,
            "online_expert_blend_promotion_gate_passed": False,
        },
        "information_boundary": {
            "all_four_target_windows_exposed_before_blend_design": True,
            "future_target_observation_used_inside_forecast": False,
            "historical_realized_action_used_by_source_models": True,
            "retrospective_nwm_forcing_used_by_source_models": True,
            "operational_issue_time_vintages_verified": False,
            "evaluation_counts_as_fresh_validation": False,
            "fresh_prospective_window_consumed": False,
        },
        "claim_boundary": {
            "physical_online_expert_blend_posthoc_executed": True,
            "online_expert_blend_admitted": False,
            "cross_system_algorithm_generalization_validated": False,
            "geospatial_kernel_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return outputs, report


def _compile_window(
    *,
    source_body: bytes,
    config: PhysicalOnlineExpertBlendConfig,
) -> tuple[bytes, dict[str, Any]]:
    source_rows = _source_rows(source_body)
    rows_by_issue: dict[datetime, list[dict[str, str]]] = defaultdict(list)
    for source in source_rows:
        rows_by_issue[cross._parse_time(source["issue_time_utc"])].append(source)
    blender = PhysicalOnlineExpertBlender(config)
    pending: list[dict[str, Any]] = []
    rows: list[dict[str, object]] = []
    active_count = 0
    clipped_count = 0
    matured_update_count = 0
    for issue_time in sorted(rows_by_issue):
        still_pending = []
        for sample in pending:
            if sample["available_at"] <= issue_time:
                blender.update(
                    sample_id=sample["sample_id"],
                    forecast_horizon_hours=sample["horizon"],
                    baseline_prediction_m3s=sample["baseline"],
                    alternative_prediction_m3s=sample["alternative"],
                    candidate_shadow_prediction_m3s=sample["shadow_prediction"],
                    candidate_evidence_gate_passed=sample["evidence_gate_passed"],
                    observed_target_m3s=sample["observed"],
                    target_observation_available_at=sample["available_at"],
                    update_time=issue_time,
                )
                matured_update_count += 1
            else:
                still_pending.append(sample)
        pending = still_pending
        for source in sorted(
            rows_by_issue[issue_time],
            key=lambda value: int(value["horizon_hours"]),
        ):
            horizon = int(source["horizon_hours"])
            baseline_prediction = float(source["physical_online_residual_adaptation_m3s"])
            alternative_prediction = float(source["action_innovation_wwm_m3s"])
            step = blender.predict(
                forecast_horizon_hours=horizon,
                baseline_prediction_m3s=baseline_prediction,
                alternative_prediction_m3s=alternative_prediction,
                issue_time=issue_time,
            )
            active_count += int(step.application_gate_passed)
            clipped_count += int(step.clipped)
            target_time = cross._parse_time(source["target_support_end_utc"])
            available_at = cross._parse_time(source["target_observation_available_at_utc"])
            rows.append(
                {
                    "system_id": source["system_id"],
                    "issue_time_utc": source["issue_time_utc"],
                    "target_support_end_utc": source["target_support_end_utc"],
                    "horizon_hours": horizon,
                    "observed_discharge_m3s": source["observed_discharge_m3s"],
                    "physical_open_loop_m3s": source["physical_open_loop_m3s"],
                    "physical_online_residual_adaptation_m3s": (baseline_prediction),
                    "action_innovation_wwm_m3s": alternative_prediction,
                    "causal_persistence_m3s": source["causal_persistence_m3s"],
                    "physical_online_expert_blend_m3s": (step.blended_prediction_m3s),
                    "online_expert_alternative_delta_m3s": (step.alternative_delta_m3s),
                    "online_expert_matured_sample_count": (step.matured_sample_count),
                    "online_expert_raw_weight": step.raw_weight,
                    "online_expert_weight_standard_error": (step.weight_standard_error),
                    "online_expert_evidence_threshold": (step.evidence_threshold),
                    "online_expert_evidence_gate_passed": (step.evidence_gate_passed),
                    "online_expert_shadow_validation_sample_count": (
                        step.shadow_validation_sample_count
                    ),
                    "online_expert_shadow_mean_squared_error_improvement_m6s2": (
                        step.shadow_mean_squared_error_improvement_m6s2
                    ),
                    "online_expert_shadow_improvement_threshold_m6s2": (
                        step.shadow_improvement_threshold_m6s2
                    ),
                    "online_expert_shadow_performance_gate_passed": (
                        step.shadow_performance_gate_passed
                    ),
                    "online_expert_shadow_weight": step.shadow_weight,
                    "online_expert_shadow_prediction_m3s": (step.shadow_prediction_m3s),
                    "online_expert_application_gate_passed": (step.application_gate_passed),
                    "online_expert_applied_weight": step.applied_weight,
                    "online_expert_correction_clipped": step.clipped,
                    "target_observation_available_at_utc": online._iso(available_at),
                    "future_target_observation_used_for_blend": False,
                    "parameter_state_transferred_between_windows": False,
                    "operational_vintages_verified": False,
                }
            )
            observed_text = source["observed_discharge_m3s"]
            if observed_text != "":
                observed = float(observed_text)
                if not math.isfinite(observed):
                    raise ValueError("physical_online_expert_blend_observation_invalid")
                pending.append(
                    {
                        "sample_id": (
                            f"{source['system_id']}:"
                            f"{source['issue_time_utc']}:{horizon}:"
                            f"{source['target_support_end_utc']}"
                        ),
                        "horizon": horizon,
                        "baseline": baseline_prediction,
                        "alternative": alternative_prediction,
                        "shadow_prediction": step.shadow_prediction_m3s,
                        "evidence_gate_passed": step.evidence_gate_passed,
                        "observed": observed,
                        "available_at": available_at,
                    }
                )
            if available_at != target_time + timedelta(hours=OBSERVATION_LATENCY_HOURS):
                raise ValueError("physical_online_expert_blend_latency_invalid")
    columns = {
        "physical_open_loop": "physical_open_loop_m3s",
        "physical_online_residual_adaptation": ("physical_online_residual_adaptation_m3s"),
        "physical_online_expert_blend": ("physical_online_expert_blend_m3s"),
        "action_innovation_wwm": "action_innovation_wwm_m3s",
        "causal_persistence": "causal_persistence_m3s",
    }
    metrics, scoring = candidate._score(rows, columns)
    return cross._encode_rows(rows), {
        "system_id": source_rows[0]["system_id"],
        "window": {
            "first_issue_time_utc": online._iso(min(rows_by_issue)),
            "last_issue_time_utc": online._iso(max(rows_by_issue)),
            "horizons_hours": list(HORIZONS),
            "online_state_reset_at_window_start": True,
        },
        "metrics_by_horizon": metrics,
        "comparison": _comparison(metrics),
        "paired_loss_diagnostic_vs_raw_physical_by_horizon": (
            _paired_loss_diagnostics(
                rows,
                reference_column="physical_open_loop_m3s",
                candidate_column="physical_online_expert_blend_m3s",
            )
        ),
        "paired_loss_diagnostic_vs_v4_by_horizon": (
            _paired_loss_diagnostics(
                rows,
                reference_column="physical_online_residual_adaptation_m3s",
                candidate_column="physical_online_expert_blend_m3s",
            )
        ),
        "scoring": scoring,
        "execution": {
            "prediction_row_count": len(rows),
            "forecast_issue_count": len(rows_by_issue),
            "matured_outcome_update_count": matured_update_count,
            "expert_blend_activated_prediction_count": active_count,
            "physical_first_fallback_prediction_count": len(rows) - active_count,
            "blended_prediction_clipped_count": clipped_count,
            "final_matured_sample_count_by_horizon": {
                str(key): value for key, value in blender.sample_count_by_horizon().items()
            },
            "future_target_observation_used_before_availability": False,
            "parameter_state_transferred_between_windows": False,
        },
    }


def _paired_loss_diagnostics(
    rows: list[Mapping[str, object]],
    *,
    reference_column: str,
    candidate_column: str,
) -> dict[str, dict[str, float | int | bool | None]]:
    diagnostics = {}
    for horizon in HORIZONS:
        improvements_by_issue: dict[datetime, float] = {}
        for row in rows:
            if int(row["horizon_hours"]) != horizon or row["observed_discharge_m3s"] == "":
                continue
            observed = float(row["observed_discharge_m3s"])
            reference = float(row[reference_column])
            prediction = float(row[candidate_column])
            issue_time = cross._parse_time(str(row["issue_time_utc"]))
            if issue_time in improvements_by_issue:
                raise ValueError("physical_online_expert_blend_paired_loss_duplicate")
            improvements_by_issue[issue_time] = (reference - observed) ** 2 - (
                prediction - observed
            ) ** 2
        improvements = [improvements_by_issue[key] for key in sorted(improvements_by_issue)]
        if not improvements:
            raise ValueError("physical_online_expert_blend_paired_loss_empty")
        sample_count = len(improvements)
        mean_improvement = sum(improvements) / sample_count
        centered = {key: value - mean_improvement for key, value in improvements_by_issue.items()}
        maximum_lag = horizon - 1
        long_run_variance = sum(value**2 for value in centered.values()) / sample_count
        for lag in range(1, maximum_lag + 1):
            autocovariance = (
                sum(
                    value * centered[issue_time - timedelta(hours=lag)]
                    for issue_time, value in centered.items()
                    if issue_time - timedelta(hours=lag) in centered
                )
                / sample_count
            )
            long_run_variance += 2.0 * (1.0 - lag / (maximum_lag + 1)) * autocovariance
        standard_error = math.sqrt(max(0.0, long_run_variance) / sample_count)
        z_score = mean_improvement / standard_error if standard_error > 0.0 else None
        diagnostics[str(horizon)] = {
            "sample_count": sample_count,
            "loss": "squared_error",
            "reference_column": reference_column,
            "candidate_column": candidate_column,
            "reference_minus_candidate_mean_squared_error_m6s2": (mean_improvement),
            "hac_max_lag": maximum_lag,
            "hac_standard_error_m6s2": standard_error,
            "improvement_z_score": z_score,
            "evidence_z_threshold": 1.96,
            "mean_improvement_exceeds_1_96_hac_standard_errors": (
                z_score is not None and z_score > 1.96
            ),
            "formal_diebold_mariano_claimed": False,
        }
    return diagnostics


def _comparison(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> dict[str, Any]:
    comparators = {
        "raw_physical": "physical_open_loop",
        "v4": "physical_online_residual_adaptation",
        "wwm": "action_innovation_wwm",
        "persistence": "causal_persistence",
    }
    per_horizon = {}
    for horizon in HORIZONS:
        values = metrics[str(horizon)]
        blend_rmse = values["physical_online_expert_blend"]["rmse_m3s"]
        per_horizon[str(horizon)] = {
            f"blend_minus_{name}_rmse_m3s": (blend_rmse - values[column]["rmse_m3s"])
            for name, column in comparators.items()
        }
    result: dict[str, Any] = {"per_horizon": per_horizon}
    for name in comparators:
        deltas = [per_horizon[str(horizon)][f"blend_minus_{name}_rmse_m3s"] for horizon in HORIZONS]
        result[f"blend_beats_{name}_all_horizons"] = all(delta < 0.0 for delta in deltas)
        result[f"blend_not_worse_than_{name}_all_horizons"] = all(delta <= 0.0 for delta in deltas)
        result[f"blend_beats_{name}_horizons_hours"] = [
            horizon for horizon, delta in zip(HORIZONS, deltas, strict=True) if delta < 0.0
        ]
    return result


def _source_rows(body: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    required = {
        "system_id",
        "issue_time_utc",
        "target_support_end_utc",
        "horizon_hours",
        "observed_discharge_m3s",
        "physical_open_loop_m3s",
        "physical_online_residual_adaptation_m3s",
        "action_innovation_wwm_m3s",
        "causal_persistence_m3s",
        "target_observation_available_at_utc",
        "operational_vintages_verified",
    }
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("physical_online_expert_blend_source_columns_invalid")
    rows = list(reader)
    if not rows:
        raise ValueError("physical_online_expert_blend_source_axis_invalid")
    system_ids = {row["system_id"] for row in rows}
    if len(system_ids) != 1:
        raise ValueError("physical_online_expert_blend_source_axis_invalid")
    for row in rows:
        issue_time = cross._parse_time(row["issue_time_utc"])
        target_time = cross._parse_time(row["target_support_end_utc"])
        horizon = int(row["horizon_hours"])
        if (
            horizon not in HORIZONS
            or target_time != issue_time + timedelta(hours=horizon)
            or row["operational_vintages_verified"] != "False"
        ):
            raise ValueError("physical_online_expert_blend_source_axis_invalid")
    return rows


def _load_source_report(
    *,
    path: Path,
    expected_schema: str,
    expected_status: str,
    execution_claim: str,
) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    outputs = report.get("outputs") or {}
    claims = report.get("claim_boundary") or {}
    information = report.get("information_boundary") or {}
    if (
        report.get("schema") != expected_schema
        or report.get("status") != expected_status
        or claims.get(execution_claim) is not True
        or claims.get("geospatial_kernel_validated") is not False
        or information.get("evaluation_counts_as_fresh_validation") is not False
        or not {"primary_predictions", "replication_predictions"}.issubset(outputs)
    ):
        raise ValueError("physical_online_expert_blend_source_report_invalid")
    return body, report


def _count_deltas(
    windows: Mapping[str, Mapping[str, Any]],
    *,
    comparator: str,
    sign: int,
) -> int:
    return sum(
        sign * values[f"blend_minus_{comparator}_rmse_m3s"] > 0.0
        for result in windows.values()
        for values in result["comparison"]["per_horizon"].values()
    )


def _default_prediction_paths() -> dict[str, Path]:
    return {name: DEFAULT_OUTPUT_ROOT / f"{name}_predictions.csv" for name in WINDOW_NAMES}


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
        raise ValueError("physical_online_expert_blend_generated_at_invalid")
    return value.astimezone(UTC)


def _json_body(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> None:
    args = parse_args()
    paths = {name: args.output_root / f"{name}_predictions.csv" for name in WINDOW_NAMES}
    bodies, report = compile_physical_online_expert_blend_posthoc(
        jpp_report_path=args.jpp_report,
        center_hill_report_path=args.center_hill_report,
        prediction_paths=paths,
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        paths[name].write_bytes(body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    for window_name in WINDOW_NAMES:
        for horizon in HORIZONS:
            values = report["windows"][window_name]["comparison"]["per_horizon"][str(horizon)]
            print(
                f"window={window_name} horizon={horizon}h "
                f"blend_minus_raw_rmse="
                f"{values['blend_minus_raw_physical_rmse_m3s']:.6f} "
                f"blend_minus_v4_rmse="
                f"{values['blend_minus_v4_rmse_m3s']:.6f}"
            )


if __name__ == "__main__":
    main()
