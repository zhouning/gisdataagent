#!/usr/bin/env python3
"""Evaluate causal target-online residual adaptation over sealed physical routing."""

from __future__ import annotations

import argparse
import hashlib
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
    from scripts import evaluate_geospatial_kernel_physical_residual_retention_transfer as retention
else:
    import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    import evaluate_geospatial_kernel_physical_residual_retention_transfer as retention

REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
CORE_OPERATOR_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/physical_online_residual_adaptation.py"
)
DEFAULT_COMPARISON_REPORT = retention.DEFAULT_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/"
    "geospatial_kernel_physical_online_residual_adaptation_posthoc"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_physical_online_residual_adaptation_posthoc_report.json"
)
SCHEMA = "gwm.geotransport.physical_online_residual_adaptation_posthoc.v1"
HORIZONS = retention.HORIZONS
TARGET_SYSTEM_ID = retention.TARGET_SYSTEM_ID
OBSERVATION_LATENCY_HOURS = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comparison-report",
        type=Path,
        default=DEFAULT_COMPARISON_REPORT,
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_physical_online_residual_adaptation_posthoc(
    *,
    comparison_report_path: Path = DEFAULT_COMPARISON_REPORT,
    primary_prediction_path: Path | None = None,
    replication_prediction_path: Path | None = None,
    generated_at: datetime | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Replay a fixed causal online algorithm; never prefit on target outcomes."""

    primary_prediction_path = primary_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_primary_predictions.csv"
    )
    replication_prediction_path = replication_prediction_path or (
        DEFAULT_OUTPUT_ROOT / "j_percy_priest_replication_predictions.csv"
    )
    comparison_body, comparison = _load_comparison_report(comparison_report_path)
    primary_source_descriptor = comparison["outputs"]["primary_predictions"]
    replication_source_descriptor = comparison["outputs"]["replication_predictions"]
    primary_source_body = cross._read_verified(primary_source_descriptor)
    replication_source_body = cross._read_verified(replication_source_descriptor)
    config = PhysicalOnlineResidualAdaptationConfig()
    config_body = _canonical_json_body(config.as_dict())

    primary_body, primary = _compile_window(primary_source_body, config=config)
    replication_body, replication = _compile_window(
        replication_source_body,
        config=config,
    )
    _verify_metric_replay(primary, comparison["primary_window"])
    _verify_metric_replay(replication, comparison["replication_window"])
    results = (primary, replication)
    beats_raw = all(
        result["comparison"]["online_beats_raw_physical_all_horizons"]
        for result in results
    )
    noninferior_raw = all(
        result["comparison"]["online_not_worse_than_raw_physical_all_horizons"]
        for result in results
    )
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
    outputs = {
        "primary_predictions": primary_body,
        "replication_predictions": replication_body,
    }
    report = {
        "schema": SCHEMA,
        "status": "causal_online_residual_adaptation_posthoc_complete",
        "generated_at": _aware_datetime(
            generated_at if generated_at is not None else datetime.now(UTC)
        ).isoformat(),
        "implementation_artifacts": {
            "online_residual_adapter": _artifact(
                CORE_OPERATOR_PATH,
                CORE_OPERATOR_PATH.read_bytes(),
            ),
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
        },
        "source_artifacts": {
            "comparison_report": _artifact(comparison_report_path, comparison_body),
            "primary_target_comparison_rows": dict(primary_source_descriptor),
            "replication_target_comparison_rows": dict(replication_source_descriptor),
        },
        "outputs": {
            "primary_predictions": _artifact(primary_prediction_path, primary_body),
            "replication_predictions": _artifact(
                replication_prediction_path,
                replication_body,
            ),
        },
        "fixed_online_contract": {
            **config.as_dict(),
            "configuration_sha256": hashlib.sha256(config_body).hexdigest(),
            "observation_latency_hours": OBSERVATION_LATENCY_HOURS,
            "one_independent_online_state_per_evaluation_window": True,
            "future_target_rows_queued_outside_model_until_available": True,
            "target_batch_prefit_performed": False,
            "source_system_parameter_transferred": False,
            "per_window_hyperparameter_tuning_performed": False,
        },
        "primary_window": primary,
        "replication_window": replication,
        "diagnostic_interpretation": {
            "online_beats_raw_physical_all_horizons_in_both_windows": beats_raw,
            "online_not_worse_than_raw_physical_all_horizons_in_both_windows": (
                noninferior_raw
            ),
            "online_beats_source_fitted_retention_all_horizons_in_both_windows": all(
                result["comparison"][
                    "online_beats_source_fitted_retention_all_horizons"
                ]
                for result in results
            ),
            "online_beats_wwm_all_horizons_in_both_windows": all(
                result["comparison"]["online_beats_wwm_all_horizons"]
                for result in results
            ),
            "raw_physical_remains_required_minimum_physical_bar": True,
            "numerical_rmse_improvement_window_horizon_count": (
                numerical_improvement_count
            ),
            "hac_supported_squared_error_improvement_window_horizon_count": (
                hac_supported_improvement_count
            ),
            "window_horizon_comparison_count": len(results) * len(HORIZONS),
            "result_may_trigger_refit_on_these_windows": False,
        },
        "promotion_gate": {
            "must_beat_raw_physical_all_horizons_in_both_windows": True,
            "accuracy_requirement_passed": beats_raw,
            "causal_maturity_ordering_passed": all(
                result["execution"]["future_target_observation_used_before_availability"]
                is False
                for result in results
            ),
            "fresh_prospective_design_required": True,
            "fresh_prospective_design_passed": False,
            "online_residual_adaptation_promotion_gate_passed": False,
        },
        "information_boundary": {
            "target_outcome_files_contain_full_historical_window": True,
            "target_outcomes_were_exposed_before_algorithm_design": True,
            "phase_lead_horizon_mapping_selected_after_target_outcome_exposure": (
                True
            ),
            "target_outcome_passed_to_adapter_before_declared_availability": False,
            "future_target_observation_used_inside_forecast": False,
            "historical_realized_action_used_by_raw_physical_rollout": True,
            "retrospective_nwm_forcing_used_by_raw_physical_rollout": True,
            "operational_issue_time_vintages_verified": False,
            "evaluation_counts_as_fresh_validation": False,
            "fresh_prospective_window_consumed": False,
        },
        "claim_boundary": {
            "physical_online_residual_adaptation_posthoc_executed": True,
            "online_adaptation_admitted": False,
            "physical_operator_admitted": False,
            "wwm_candidate_admitted": False,
            "geospatial_kernel_validated": False,
            "multi_system_generalization_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }
    return outputs, report


def _compile_window(
    source_body: bytes,
    *,
    config: PhysicalOnlineResidualAdaptationConfig,
) -> tuple[bytes, dict[str, Any]]:
    source_rows = retention._comparison_rows(source_body)
    rows_by_issue: dict[datetime, list[dict[str, str]]] = defaultdict(list)
    for source in source_rows:
        rows_by_issue[cross._parse_time(source["issue_time_utc"])].append(source)
    adapter = PhysicalOnlineResidualAdapter(config)
    pending: list[dict[str, Any]] = []
    rows: list[dict[str, object]] = []
    clipped_count = 0
    active_count = 0
    matured_update_count = 0
    finite_negative_outcome_update_count = 0
    nonfinite_outcome_update_count = 0
    for issue_time in sorted(rows_by_issue):
        still_pending = []
        for sample in pending:
            if sample["available_at"] <= issue_time:
                adapter.update(
                    sample_id=sample["sample_id"],
                    forecast_horizon_hours=sample["horizon"],
                    physical_trajectory_change_m3s=sample[
                        "physical_trajectory_change"
                    ],
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
        for source in sorted(
            rows_by_issue[issue_time],
            key=lambda value: int(value["horizon_hours"]),
        ):
            horizon = int(source["horizon_hours"])
            physical = float(source["physical_open_loop_m3s"])
            latest_residual = float(source["latest_observation_residual_m3s"])
            physical_at_latest = float(
                source["physical_at_latest_observation_m3s"]
            )
            predictor_horizon = dict(
                config.trajectory_predictor_horizon_pairs
            ).get(horizon)
            issue_rows_by_horizon = {
                int(value["horizon_hours"]): value
                for value in rows_by_issue[issue_time]
            }
            predictor_source = (
                issue_rows_by_horizon.get(predictor_horizon)
                if predictor_horizon is not None
                else None
            )
            predictor_physical = (
                float(predictor_source["physical_open_loop_m3s"])
                if predictor_source is not None
                else None
            )
            step = adapter.predict(
                forecast_horizon_hours=horizon,
                physical_at_latest_observation_m3s=physical_at_latest,
                predictor_physical_target_m3s=predictor_physical,
                physical_target_m3s=physical,
                issue_time=issue_time,
            )
            active_count += int(step.application_gate_passed)
            clipped_count += int(step.clipped)
            rows.append(
                {
                    "system_id": source["system_id"],
                    "issue_time_utc": source["issue_time_utc"],
                    "target_support_end_utc": source["target_support_end_utc"],
                    "horizon_hours": horizon,
                    "observed_discharge_m3s": source["observed_discharge_m3s"],
                    "physical_open_loop_m3s": source["physical_open_loop_m3s"],
                    "physical_online_residual_adaptation_m3s": (
                        step.corrected_prediction_m3s
                    ),
                    "physical_residual_retention_m3s": source[
                        "physical_residual_retention_m3s"
                    ],
                    "physical_residual_decay_m3s": source[
                        "physical_residual_decay_m3s"
                    ],
                    "classical_arx_m3s": source["classical_arx_m3s"],
                    "action_innovation_wwm_m3s": source[
                        "action_innovation_wwm_m3s"
                    ],
                    "causal_persistence_m3s": source["causal_persistence_m3s"],
                    "physical_at_latest_observation_m3s": physical_at_latest,
                    "latest_observation_residual_m3s": latest_residual,
                    "online_physical_trajectory_change_m3s": (
                        step.physical_trajectory_change_m3s
                    ),
                    "online_predictor_forecast_horizon_hours": (
                        step.predictor_forecast_horizon_hours
                    ),
                    "online_predictor_physical_target_m3s": (
                        step.predictor_physical_target_m3s
                    ),
                    "online_matured_sample_count": step.matured_sample_count,
                    "online_raw_weight": step.raw_weight,
                    "online_weight_standard_error": step.weight_standard_error,
                    "online_evidence_threshold": step.evidence_threshold,
                    "online_correction_mode": step.correction_mode,
                    "online_raw_bias_m3s": step.raw_bias_m3s,
                    "online_bias_standard_error_m3s": (
                        step.bias_standard_error_m3s
                    ),
                    "online_bias_evidence_threshold_m3s": (
                        step.bias_evidence_threshold_m3s
                    ),
                    "online_evidence_gate_passed": step.evidence_gate_passed,
                    "online_shadow_validation_sample_count": (
                        step.shadow_validation_sample_count
                    ),
                    "online_shadow_rmse_m3s": step.shadow_rmse_m3s,
                    "online_raw_physical_rmse_m3s": step.raw_physical_rmse_m3s,
                    "online_shadow_mean_squared_error_improvement_m6s2": (
                        step.shadow_mean_squared_error_improvement_m6s2
                    ),
                    "online_shadow_improvement_standard_error_m6s2": (
                        step.shadow_improvement_standard_error_m6s2
                    ),
                    "online_shadow_improvement_threshold_m6s2": (
                        step.shadow_improvement_threshold_m6s2
                    ),
                    "online_shadow_performance_gate_passed": (
                        step.shadow_performance_gate_passed
                    ),
                    "online_shadow_weight": step.shadow_weight,
                    "online_shadow_bias_m3s": step.shadow_bias_m3s,
                    "online_shadow_prediction_m3s": step.shadow_prediction_m3s,
                    "online_application_gate_passed": step.application_gate_passed,
                    "online_applied_weight": step.applied_weight,
                    "online_applied_bias_m3s": step.applied_bias_m3s,
                    "online_correction_clipped": step.clipped,
                    "target_observation_available_at_utc": _iso(
                        cross._parse_time(source["target_support_end_utc"])
                        + timedelta(hours=OBSERVATION_LATENCY_HOURS)
                    ),
                    "future_target_observation_used_for_correction": False,
                    "target_batch_prefit_performed": False,
                    "operational_vintages_verified": False,
                }
            )
            observed_text = source["observed_discharge_m3s"]
            if observed_text != "":
                target_time = cross._parse_time(source["target_support_end_utc"])
                observed = float(observed_text)
                predictor_available = (
                    step.physical_trajectory_change_m3s is not None
                    or horizon
                    in config.bias_adaptive_forecast_horizons_hours
                )
                if math.isfinite(observed) and predictor_available:
                    pending.append(
                        {
                            "sample_id": (
                                f"{source['issue_time_utc']}:{horizon}:"
                                f"{source['target_support_end_utc']}"
                            ),
                            "horizon": horizon,
                            "physical_trajectory_change": (
                                step.physical_trajectory_change_m3s or 0.0
                            ),
                            "physical_target": physical,
                            "shadow_prediction": step.shadow_prediction_m3s,
                            "evidence_gate_passed": step.evidence_gate_passed,
                            "observed_target": observed,
                            "available_at": target_time
                            + timedelta(hours=OBSERVATION_LATENCY_HOURS),
                        }
                    )
                    finite_negative_outcome_update_count += int(observed < 0.0)
                elif not math.isfinite(observed):
                    nonfinite_outcome_update_count += 1
    columns = {
        "physical_open_loop": "physical_open_loop_m3s",
        "physical_online_residual_adaptation": (
            "physical_online_residual_adaptation_m3s"
        ),
        "physical_residual_retention": "physical_residual_retention_m3s",
        "physical_residual_decay": "physical_residual_decay_m3s",
        "classical_arx": "classical_arx_m3s",
        "action_innovation_wwm": "action_innovation_wwm_m3s",
        "causal_persistence": "causal_persistence_m3s",
    }
    metrics, scoring = candidate._score(rows, columns)
    return cross._encode_rows(rows), {
        "window": {
            "first_issue_time_utc": _iso(min(rows_by_issue)),
            "last_issue_time_utc": _iso(max(rows_by_issue)),
            "horizons_hours": list(HORIZONS),
            "online_state_reset_at_window_start": True,
        },
        "metrics_by_horizon": metrics,
        "comparison": _comparison(metrics),
        "paired_loss_diagnostic_by_horizon": _paired_loss_diagnostics(rows),
        "scoring": scoring,
        "execution": {
            "prediction_row_count": len(rows),
            "forecast_issue_count": len(rows_by_issue),
            "matured_outcome_update_count": matured_update_count,
            "evidence_activated_prediction_count": active_count,
            "raw_physical_fallback_prediction_count": len(rows) - active_count,
            "corrected_prediction_clipped_count": clipped_count,
            "finite_negative_outcome_queued_for_online_update_count": (
                finite_negative_outcome_update_count
            ),
            "nonfinite_outcome_excluded_from_online_update_count": (
                nonfinite_outcome_update_count
            ),
            "final_matured_sample_count_by_horizon": {
                str(key): value
                for key, value in adapter.sample_count_by_horizon().items()
            },
            "future_target_observation_used_before_availability": False,
            "target_batch_prefit_performed": False,
        },
    }


def _paired_loss_diagnostics(
    rows: list[Mapping[str, object]],
) -> dict[str, dict[str, float | int | bool | None]]:
    """Summarize paired squared-error gains with horizon-overlap HAC variance."""

    diagnostics: dict[str, dict[str, float | int | bool | None]] = {}
    for horizon in HORIZONS:
        improvements_by_issue: dict[datetime, float] = {}
        for row in rows:
            if (
                int(row["horizon_hours"]) != horizon
                or row["observed_discharge_m3s"] == ""
            ):
                continue
            observed = float(row["observed_discharge_m3s"])
            physical = float(row["physical_open_loop_m3s"])
            online = float(row["physical_online_residual_adaptation_m3s"])
            issue_time = cross._parse_time(str(row["issue_time_utc"]))
            if issue_time in improvements_by_issue:
                raise ValueError(
                    "physical_online_residual_adaptation_paired_loss_duplicate"
                )
            improvements_by_issue[issue_time] = (
                (physical - observed) ** 2 - (online - observed) ** 2
            )
        improvements = [
            improvements_by_issue[key] for key in sorted(improvements_by_issue)
        ]
        sample_count = len(improvements)
        if not improvements:
            raise ValueError(
                "physical_online_residual_adaptation_paired_loss_empty"
            )
        mean_improvement = sum(improvements) / sample_count
        centered_by_issue = {
            key: value - mean_improvement
            for key, value in improvements_by_issue.items()
        }
        maximum_lag = horizon - 1
        long_run_variance = (
            sum(value**2 for value in centered_by_issue.values()) / sample_count
        )
        for lag in range(1, maximum_lag + 1):
            autocovariance = sum(
                value * centered_by_issue[issue_time - timedelta(hours=lag)]
                for issue_time, value in centered_by_issue.items()
                if issue_time - timedelta(hours=lag) in centered_by_issue
            ) / sample_count
            long_run_variance += (
                2.0 * (1.0 - lag / (maximum_lag + 1)) * autocovariance
            )
        standard_error = math.sqrt(max(0.0, long_run_variance) / sample_count)
        z_score = (
            mean_improvement / standard_error if standard_error > 0.0 else None
        )
        diagnostics[str(horizon)] = {
            "sample_count": sample_count,
            "loss": "squared_error",
            "raw_minus_online_mean_squared_error_m6s2": mean_improvement,
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
        "source_fitted_retention": "physical_residual_retention",
        "source_fitted_decay": "physical_residual_decay",
        "arx": "classical_arx",
        "wwm": "action_innovation_wwm",
        "persistence": "causal_persistence",
    }
    per_horizon = {}
    for horizon in HORIZONS:
        values = metrics[str(horizon)]
        online_rmse = values["physical_online_residual_adaptation"]["rmse_m3s"]
        per_horizon[str(horizon)] = {
            f"online_minus_{name}_rmse_m3s": (
                online_rmse - values[column]["rmse_m3s"]
            )
            for name, column in comparators.items()
        }
    result: dict[str, Any] = {"per_horizon": per_horizon}
    for name in comparators:
        deltas = [
            per_horizon[str(horizon)][f"online_minus_{name}_rmse_m3s"]
            for horizon in HORIZONS
        ]
        result[f"online_beats_{name}_all_horizons"] = all(
            delta < 0.0 for delta in deltas
        )
        result[f"online_not_worse_than_{name}_all_horizons"] = all(
            delta <= 0.0 for delta in deltas
        )
        result[f"online_beats_{name}_horizons_hours"] = [
            horizon for horizon, delta in zip(HORIZONS, deltas, strict=True) if delta < 0.0
        ]
    return result


def _load_comparison_report(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    outputs = report.get("outputs") or {}
    claims = report.get("claim_boundary") or {}
    if (
        report.get("schema") != retention.SCHEMA
        or report.get("status")
        != "source_fitted_physical_residual_retention_transfer_posthoc_complete"
        or claims.get("physical_residual_retention_posthoc_executed") is not True
        or claims.get("geospatial_kernel_validated") is not False
        or not {"primary_predictions", "replication_predictions"}.issubset(outputs)
    ):
        raise ValueError("physical_online_residual_adaptation_comparison_report_invalid")
    return body, report


def _verify_metric_replay(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    existing_models = (
        "physical_open_loop",
        "physical_residual_retention",
        "physical_residual_decay",
        "classical_arx",
        "action_innovation_wwm",
        "causal_persistence",
    )
    for horizon in HORIZONS:
        actual_metrics = actual["metrics_by_horizon"][str(horizon)]
        prior_metrics = expected["metrics_by_horizon"][str(horizon)]
        for model_name in existing_models:
            if actual_metrics[model_name] != prior_metrics[model_name]:
                raise ValueError(
                    "physical_online_residual_adaptation_metric_replay_mismatch"
                )
    if actual["scoring"] != expected["scoring"]:
        raise ValueError("physical_online_residual_adaptation_scoring_replay_mismatch")


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    return {
        "path": cross._display(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _canonical_json_body(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _json_body(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("physical_online_residual_adaptation_generated_at_invalid")
    return value.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def main() -> None:
    args = parse_args()
    paths = {
        "primary_predictions": (
            args.output_root / "j_percy_priest_primary_predictions.csv"
        ),
        "replication_predictions": (
            args.output_root / "j_percy_priest_replication_predictions.csv"
        ),
    }
    bodies, report = compile_physical_online_residual_adaptation_posthoc(
        comparison_report_path=args.comparison_report,
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
                f"{values['online_minus_raw_physical_rmse_m3s']:.6f} "
                f"online_minus_retention_rmse="
                f"{values['online_minus_source_fitted_retention_rmse_m3s']:.6f}"
            )


if __name__ == "__main__":
    main()
