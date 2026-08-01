#!/usr/bin/env python3
"""Compare v5 with simple causal online expert-selection baselines."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.online_expert_evaluation import (
    external_regret_to_best_fixed_constituent,
)
from data_agent.uwm.geospatial_kernel_v2.physical_online_expert_blend import (
    PhysicalOnlineExpertBlendConfig,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    from scripts import evaluate_geospatial_kernel_physical_online_expert_blend as blend
    from scripts import evaluate_geospatial_kernel_physical_online_residual_adaptation as online
else:
    import evaluate_geospatial_kernel_action_innovation_candidate as candidate
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    import evaluate_geospatial_kernel_physical_online_expert_blend as blend
    import evaluate_geospatial_kernel_physical_online_residual_adaptation as online


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
ONLINE_EXPERT_EVALUATION_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/online_expert_evaluation.py"
)
DEFAULT_SOURCE_REPORT = blend.DEFAULT_REPORT
DEFAULT_OUTPUT_ROOT = REPO_ROOT / (
    "data/geotransport_v0_1/geospatial_kernel_online_expert_traditional_baselines_posthoc"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_online_expert_traditional_baselines_posthoc_report.json"
)
SCHEMA = "gwm.geotransport.online_expert_traditional_baselines_posthoc.v1"
WINDOW_NAMES = blend.WINDOW_NAMES
HORIZONS = blend.HORIZONS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-report",
        type=Path,
        default=DEFAULT_SOURCE_REPORT,
    )
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_online_expert_traditional_baselines_posthoc(
    *,
    source_report_path: Path = DEFAULT_SOURCE_REPORT,
    prediction_paths: Mapping[str, Path] | None = None,
    generated_at: datetime | None = None,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    """Replay fixed equal blending and evidence-gated follow-the-leader."""

    prediction_paths = dict(prediction_paths or _default_prediction_paths())
    if set(prediction_paths) != set(WINDOW_NAMES):
        raise ValueError("online_expert_traditional_output_paths_invalid")
    source_report_body, source_report = _load_source_report(source_report_path)
    descriptors = source_report["outputs"]
    config = PhysicalOnlineExpertBlendConfig()
    outputs = {}
    windows = {}
    for name in WINDOW_NAMES:
        source_body = cross._read_verified(descriptors[name])
        output_body, result = _compile_window(
            source_body=source_body,
            config=config,
        )
        outputs[name] = output_body
        windows[name] = result

    selector_vs_raw_improvements = _count_deltas(
        windows,
        model="selector",
        comparator="raw_physical",
        sign=-1,
    )
    selector_vs_v5_improvements = _count_deltas(
        windows,
        model="selector",
        comparator="v5",
        sign=-1,
    )
    selector_vs_v5_regressions = _count_deltas(
        windows,
        model="selector",
        comparator="v5",
        sign=1,
    )
    selector_vs_v5_equal = len(WINDOW_NAMES) * len(HORIZONS) - (
        selector_vs_v5_improvements + selector_vs_v5_regressions
    )
    selector_beats_raw = all(
        result["comparison"]["selector_beats_raw_physical_all_horizons"]
        for result in windows.values()
    )
    selector_noninferior_v4 = all(
        result["comparison"]["selector_not_worse_than_v4_all_horizons"]
        for result in windows.values()
    )
    selector_noninferior_v5 = all(
        result["comparison"]["selector_not_worse_than_v5_all_horizons"]
        for result in windows.values()
    )
    v5_lower_external_regret_count = sum(
        result["external_regret_to_best_fixed_constituent"][
            "v5_lower_final_average_external_regret_than_selector"
        ]
        for result in windows.values()
    )
    selector_lower_external_regret_count = sum(
        result["external_regret_to_best_fixed_constituent"][
            "selector_lower_final_average_external_regret_than_v5"
        ]
        for result in windows.values()
    )
    equal_external_regret_count = len(WINDOW_NAMES) - (
        v5_lower_external_regret_count + selector_lower_external_regret_count
    )
    warmup_counts = {
        candidate_name: {
            comparator: {
                "improvement": _count_warmup_ablation_deltas(
                    windows,
                    candidate=candidate_name,
                    comparator=comparator,
                    sign=-1,
                ),
                "regression": _count_warmup_ablation_deltas(
                    windows,
                    candidate=candidate_name,
                    comparator=comparator,
                    sign=1,
                ),
            }
            for comparator in ("v4", "v5", "selector")
        }
        for candidate_name in (
            "coefficient_lcb_blend",
            "loss_gated_lcb_blend",
            "loss_gated_ols_blend",
        )
    }
    return outputs, {
        "schema": SCHEMA,
        "status": "online_expert_traditional_baselines_posthoc_complete",
        "generated_at": _aware_datetime(
            generated_at if generated_at is not None else datetime.now(UTC)
        ).isoformat(),
        "implementation_artifacts": {
            "evaluator": _artifact(EVALUATOR_PATH, EVALUATOR_PATH.read_bytes()),
            "online_expert_evaluation": _artifact(
                ONLINE_EXPERT_EVALUATION_PATH,
                ONLINE_EXPERT_EVALUATION_PATH.read_bytes(),
            ),
        },
        "source_artifacts": {
            "v5_online_expert_blend_report": _artifact(
                source_report_path,
                source_report_body,
            ),
            "v5_predictions_by_window": {name: dict(descriptors[name]) for name in WINDOW_NAMES},
        },
        "outputs": {
            name: _artifact(prediction_paths[name], outputs[name]) for name in WINDOW_NAMES
        },
        "traditional_baseline_contract": {
            "baseline_expert": "physical_online_residual_adaptation_v4",
            "alternative_expert": "action_innovation_wwm",
            "fixed_equal_blend_formula": "0.5 * v4 + 0.5 * WWM",
            "evidence_gated_follow_the_leader_formula": (
                "WWM if matured_mean(v4_squared_error - WWM_squared_error) "
                "> 1.96 * standard_error else v4"
            ),
            "minimum_matured_sample_count": (config.minimum_matured_sample_count),
            "evidence_z_threshold": config.evidence_z_threshold,
            "one_independent_state_per_window_and_horizon": True,
            "parameter_state_transferred_between_systems_or_windows": False,
            "future_target_rows_queued_outside_model_until_available": True,
            "hyperparameter_parity_with_v5": True,
            "external_regret_definition": (
                "algorithm cumulative squared loss minus the smaller cumulative "
                "squared loss of fixed v4 or fixed WWM at each issue-time prefix"
            ),
            "warmup_ablation_formulas": {
                "coefficient_lcb_blend": (
                    "v4 + clip(raw_weight - 1.96 * weight_standard_error, 0, 1) "
                    "* (WWM - v4) after 24 matured samples"
                ),
                "loss_gated_lcb_blend": (
                    "coefficient_lcb_blend only while the matured paired-loss "
                    "Follow-the-Leader evidence gate selects WWM; otherwise v4"
                ),
                "loss_gated_ols_blend": (
                    "v4 + clip(raw_weight, 0, 1) * (WWM - v4) only while the "
                    "matured paired-loss Follow-the-Leader evidence gate selects WWM"
                ),
            },
        },
        "windows": windows,
        "diagnostic_interpretation": {
            "selector_beats_raw_physical_all_horizons_in_all_four_windows": (selector_beats_raw),
            "selector_not_worse_than_v4_all_horizons_in_all_four_windows": (
                selector_noninferior_v4
            ),
            "selector_not_worse_than_v5_all_horizons_in_all_four_windows": (
                selector_noninferior_v5
            ),
            "selector_rmse_improvement_vs_raw_physical_count": (selector_vs_raw_improvements),
            "selector_rmse_improvement_vs_v5_count": (selector_vs_v5_improvements),
            "selector_rmse_regression_vs_v5_count": (selector_vs_v5_regressions),
            "selector_rmse_equal_to_v5_count": selector_vs_v5_equal,
            "selector_strictly_dominates_v5": selector_noninferior_v5
            and selector_vs_v5_improvements > 0,
            "v5_strictly_dominates_selector": all(
                result["comparison"]["v5_not_worse_than_selector_all_horizons"]
                for result in windows.values()
            )
            and selector_vs_v5_regressions > 0,
            "traditional_selector_and_v5_have_empirical_tradeoff": (
                selector_vs_v5_improvements > 0 and selector_vs_v5_regressions > 0
            ),
            "v5_lower_final_average_external_regret_window_count": (v5_lower_external_regret_count),
            "selector_lower_final_average_external_regret_window_count": (
                selector_lower_external_regret_count
            ),
            "v5_selector_equal_final_average_external_regret_window_count": (
                equal_external_regret_count
            ),
            "external_regret_result_is_posthoc": True,
            "result_may_trigger_refit_on_these_windows": False,
        },
        "warmup_ablation_interpretation": {
            "window_horizon_comparison_count": len(WINDOW_NAMES) * len(HORIZONS),
            "counts": warmup_counts,
            "coefficient_lcb_breaks_v4_nonregression": (
                warmup_counts["coefficient_lcb_blend"]["v4"]["regression"] > 0
            ),
            "loss_gated_lcb_strictly_dominated_by_selector": (
                warmup_counts["loss_gated_lcb_blend"]["selector"]["improvement"] == 0
                and warmup_counts["loss_gated_lcb_blend"]["selector"]["regression"] > 0
            ),
            "loss_gated_ols_dominates_v5_and_selector": (
                warmup_counts["loss_gated_ols_blend"]["v5"]["regression"] == 0
                and warmup_counts["loss_gated_ols_blend"]["selector"]["regression"] == 0
                and (
                    warmup_counts["loss_gated_ols_blend"]["v5"]["improvement"] > 0
                    or warmup_counts["loss_gated_ols_blend"]["selector"]["improvement"] > 0
                )
            ),
            "any_ablation_admitted_as_new_candidate": False,
            "prospective_primary_candidate_changed": False,
            "result_may_trigger_refit_on_these_windows": False,
        },
        "promotion_gate": {
            "traditional_baseline_comparison_required": True,
            "traditional_baseline_comparison_completed": True,
            "candidate_must_strictly_dominate_traditional_selector": False,
            "fresh_prospective_design_required": True,
            "fresh_prospective_design_passed": False,
            "traditional_baseline_or_v5_promoted": False,
        },
        "information_boundary": {
            "all_four_target_windows_exposed_before_baseline_design": True,
            "future_target_observation_used_inside_forecast": False,
            "operational_issue_time_vintages_verified": False,
            "evaluation_counts_as_fresh_validation": False,
            "fresh_prospective_window_consumed": False,
        },
        "claim_boundary": {
            "traditional_online_baselines_posthoc_executed": True,
            "warmup_ablation_supports_replacing_v5": False,
            "v5_algorithmic_superiority_validated": False,
            "traditional_selector_admitted": False,
            "geospatial_kernel_validated": False,
            "runtime_default_enabled": False,
        },
    }


def _compile_window(
    *,
    source_body: bytes,
    config: PhysicalOnlineExpertBlendConfig,
) -> tuple[bytes, dict[str, Any]]:
    source_rows = _source_rows(source_body)
    rows_by_issue: dict[datetime, list[dict[str, str]]] = defaultdict(list)
    for source in source_rows:
        rows_by_issue[cross._parse_time(source["issue_time_utc"])].append(source)
    losses: dict[int, list[tuple[float, float]]] = {horizon: [] for horizon in HORIZONS}
    pending: list[dict[str, Any]] = []
    rows: list[dict[str, object]] = []
    selected_count = 0
    warmup_ablation_active_counts = {
        "coefficient_lcb_blend": 0,
        "loss_gated_lcb_blend": 0,
        "loss_gated_ols_blend": 0,
    }
    matured_update_count = 0
    for issue_time in sorted(rows_by_issue):
        still_pending = []
        for sample in pending:
            if sample["available_at"] <= issue_time:
                losses[sample["horizon"]].append(
                    (sample["baseline_loss"], sample["alternative_loss"])
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
            v4 = float(source["physical_online_residual_adaptation_m3s"])
            wwm = float(source["action_innovation_wwm_m3s"])
            selected, mean_improvement, standard_error, threshold = _alternative_gate(
                losses[horizon],
                config=config,
            )
            selector_prediction = wwm if selected else v4
            equal_blend_prediction = max(0.0, 0.5 * v4 + 0.5 * wwm)
            matured_count = int(source["online_expert_matured_sample_count"])
            raw_weight = float(source["online_expert_raw_weight"])
            threshold_text = source["online_expert_evidence_threshold"]
            coefficient_lcb_weight = 0.0
            if matured_count >= config.minimum_matured_sample_count and threshold_text != "":
                coefficient_lcb_weight = min(
                    config.weight_upper_bound,
                    max(
                        config.weight_lower_bound,
                        raw_weight - float(threshold_text),
                    ),
                )
            loss_gated_lcb_weight = coefficient_lcb_weight if selected else 0.0
            loss_gated_ols_weight = (
                min(
                    config.weight_upper_bound,
                    max(config.weight_lower_bound, raw_weight),
                )
                if selected
                else 0.0
            )
            alternative_delta = wwm - v4
            coefficient_lcb_prediction = max(
                0.0,
                v4 + coefficient_lcb_weight * alternative_delta,
            )
            loss_gated_lcb_prediction = max(
                0.0,
                v4 + loss_gated_lcb_weight * alternative_delta,
            )
            loss_gated_ols_prediction = max(
                0.0,
                v4 + loss_gated_ols_weight * alternative_delta,
            )
            selected_count += int(selected)
            warmup_ablation_active_counts["coefficient_lcb_blend"] += int(
                coefficient_lcb_weight > 0.0
            )
            warmup_ablation_active_counts["loss_gated_lcb_blend"] += int(
                loss_gated_lcb_weight > 0.0
            )
            warmup_ablation_active_counts["loss_gated_ols_blend"] += int(
                loss_gated_ols_weight > 0.0
            )
            available_at = cross._parse_time(source["target_observation_available_at_utc"])
            rows.append(
                {
                    **source,
                    "horizon_hours": horizon,
                    "fixed_equal_expert_blend_m3s": equal_blend_prediction,
                    "evidence_gated_follow_the_leader_m3s": (selector_prediction),
                    "coefficient_lcb_blend_m3s": coefficient_lcb_prediction,
                    "loss_gated_lcb_blend_m3s": loss_gated_lcb_prediction,
                    "loss_gated_ols_blend_m3s": loss_gated_ols_prediction,
                    "coefficient_lcb_weight": coefficient_lcb_weight,
                    "loss_gated_lcb_weight": loss_gated_lcb_weight,
                    "loss_gated_ols_weight": loss_gated_ols_weight,
                    "selector_matured_sample_count": len(losses[horizon]),
                    "selector_v4_minus_wwm_mean_squared_error_m6s2": (mean_improvement),
                    "selector_improvement_standard_error_m6s2": (standard_error),
                    "selector_improvement_threshold_m6s2": threshold,
                    "selector_wwm_selected": selected,
                    "future_target_observation_used_for_selector": False,
                    "selector_state_transferred_between_windows": False,
                }
            )
            observed_text = source["observed_discharge_m3s"]
            if observed_text != "":
                observed = float(observed_text)
                if not math.isfinite(observed):
                    raise ValueError("online_expert_traditional_observation_invalid")
                pending.append(
                    {
                        "available_at": available_at,
                        "horizon": horizon,
                        "baseline_loss": (v4 - observed) ** 2,
                        "alternative_loss": (wwm - observed) ** 2,
                    }
                )
    columns = {
        "physical_open_loop": "physical_open_loop_m3s",
        "v4": "physical_online_residual_adaptation_m3s",
        "v5": "physical_online_expert_blend_m3s",
        "wwm": "action_innovation_wwm_m3s",
        "persistence": "causal_persistence_m3s",
        "fixed_equal_blend": "fixed_equal_expert_blend_m3s",
        "selector": "evidence_gated_follow_the_leader_m3s",
        "coefficient_lcb_blend": "coefficient_lcb_blend_m3s",
        "loss_gated_lcb_blend": "loss_gated_lcb_blend_m3s",
        "loss_gated_ols_blend": "loss_gated_ols_blend_m3s",
    }
    metrics, scoring = candidate._score(rows, columns)
    return cross._encode_rows(rows), {
        "system_id": source_rows[0]["system_id"],
        "window": {
            "first_issue_time_utc": online._iso(min(rows_by_issue)),
            "last_issue_time_utc": online._iso(max(rows_by_issue)),
            "horizons_hours": list(HORIZONS),
            "selector_state_reset_at_window_start": True,
        },
        "metrics_by_horizon": metrics,
        "comparison": _comparison(metrics),
        "warmup_ablation": _warmup_ablation(metrics),
        "paired_loss_diagnostic_selector_vs_v5_by_horizon": (
            blend._paired_loss_diagnostics(
                rows,
                reference_column="physical_online_expert_blend_m3s",
                candidate_column="evidence_gated_follow_the_leader_m3s",
            )
        ),
        "external_regret_to_best_fixed_constituent": _external_regret_diagnostic(rows),
        "scoring": scoring,
        "execution": {
            "prediction_row_count": len(rows),
            "forecast_issue_count": len(rows_by_issue),
            "matured_outcome_update_count": matured_update_count,
            "wwm_selected_prediction_count": selected_count,
            "v4_fallback_prediction_count": len(rows) - selected_count,
            "warmup_ablation_active_prediction_counts": warmup_ablation_active_counts,
            "future_target_observation_used_before_availability": False,
            "selector_state_transferred_between_windows": False,
        },
    }


def _warmup_ablation(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> dict[str, Any]:
    candidates = (
        "coefficient_lcb_blend",
        "loss_gated_lcb_blend",
        "loss_gated_ols_blend",
    )
    comparators = {"v4": "v4", "v5": "v5", "selector": "selector"}
    per_horizon: dict[str, Any] = {}
    for horizon in HORIZONS:
        values = metrics[str(horizon)]
        per_horizon[str(horizon)] = {
            f"{candidate_name}_minus_{comparator}_rmse_m3s": (
                values[candidate_name]["rmse_m3s"] - values[comparator_column]["rmse_m3s"]
            )
            for candidate_name in candidates
            for comparator, comparator_column in comparators.items()
        }
    return {
        "comparison_role": "posthoc_warmup_ablation_not_candidate_selection",
        "per_horizon": per_horizon,
        "future_target_observation_used_inside_prediction": False,
        "result_may_trigger_refit_on_these_windows": False,
    }


def _external_regret_diagnostic(rows: list[dict[str, object]]) -> dict[str, Any]:
    per_horizon: dict[str, Any] = {}
    v5_final_average_values = []
    selector_final_average_values = []
    for horizon in HORIZONS:
        values = sorted(
            (
                row
                for row in rows
                if row["horizon_hours"] == horizon and row["observed_discharge_m3s"] != ""
            ),
            key=lambda row: (
                cross._parse_time(row["issue_time_utc"]),
                cross._parse_time(row["target_support_end_utc"]),
            ),
        )
        observed = [float(row["observed_discharge_m3s"]) for row in values]
        v5_errors = [
            float(row["physical_online_expert_blend_m3s"]) - target
            for row, target in zip(values, observed, strict=True)
        ]
        selector_errors = [
            float(row["evidence_gated_follow_the_leader_m3s"]) - target
            for row, target in zip(values, observed, strict=True)
        ]
        v4_errors = [
            float(row["physical_online_residual_adaptation_m3s"]) - target
            for row, target in zip(values, observed, strict=True)
        ]
        wwm_errors = [
            float(row["action_innovation_wwm_m3s"]) - target
            for row, target in zip(values, observed, strict=True)
        ]
        v5_regret = external_regret_to_best_fixed_constituent(
            algorithm_errors=v5_errors,
            v4_errors=v4_errors,
            wwm_errors=wwm_errors,
        )
        selector_regret = external_regret_to_best_fixed_constituent(
            algorithm_errors=selector_errors,
            v4_errors=v4_errors,
            wwm_errors=wwm_errors,
        )
        v5_final_average = v5_regret["final_average_per_case_m6s2"]
        selector_final_average = selector_regret["final_average_per_case_m6s2"]
        if v5_final_average is None or selector_final_average is None:
            raise ValueError("online_expert_traditional_external_regret_axis_invalid")
        v5_final_average_values.append(v5_final_average)
        selector_final_average_values.append(selector_final_average)
        v4_loss = sum(error**2 for error in v4_errors)
        wwm_loss = sum(error**2 for error in wwm_errors)
        per_horizon[str(horizon)] = {
            "complete_case_count": len(values),
            "best_fixed_constituent_expert_in_hindsight": (
                "physical_online_residual_adaptation_v4"
                if v4_loss < wwm_loss
                else "action_innovation_wwm"
                if wwm_loss < v4_loss
                else "tie"
            ),
            "v5": v5_regret,
            "selector": selector_regret,
            "v5_minus_selector_final_cumulative_squared_error_m6s2": (
                v5_regret["final_cumulative_m6s2"] - selector_regret["final_cumulative_m6s2"]
            ),
        }
    v5_macro = sum(v5_final_average_values) / len(HORIZONS)
    selector_macro = sum(selector_final_average_values) / len(HORIZONS)
    return {
        "comparison_selected_after_outcome_access": True,
        "comparison_role": "posthoc_time_ordered_diagnostic_not_promotion_gate",
        "per_horizon": per_horizon,
        "equal_horizon_macro_mean_final_average_external_regret_m6s2": {
            "v5": v5_macro,
            "selector": selector_macro,
        },
        "v5_lower_final_average_external_regret_than_selector": v5_macro < selector_macro,
        "selector_lower_final_average_external_regret_than_v5": selector_macro < v5_macro,
    }


def _alternative_gate(
    losses: list[tuple[float, float]],
    *,
    config: PhysicalOnlineExpertBlendConfig,
) -> tuple[bool, float | None, float | None, float | None]:
    if not losses:
        return False, None, None, None
    improvements = [baseline - alternative for baseline, alternative in losses]
    mean_improvement = sum(improvements) / len(improvements)
    if len(losses) < 2:
        return False, mean_improvement, None, None
    variance = sum((value - mean_improvement) ** 2 for value in improvements) / (
        len(improvements) - 1
    )
    standard_error = math.sqrt(max(0.0, variance) / len(improvements))
    threshold = config.evidence_z_threshold * standard_error
    selected = len(losses) >= config.minimum_matured_sample_count and mean_improvement > threshold
    return selected, mean_improvement, standard_error, threshold


def _comparison(
    metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
) -> dict[str, Any]:
    models = {
        "selector": "selector",
        "v5": "v5",
    }
    comparators = {
        "raw_physical": "physical_open_loop",
        "v4": "v4",
        "v5": "v5",
        "selector": "selector",
        "wwm": "wwm",
        "persistence": "persistence",
        "fixed_equal_blend": "fixed_equal_blend",
    }
    per_horizon: dict[str, dict[str, float]] = {}
    for horizon in HORIZONS:
        values = metrics[str(horizon)]
        horizon_result = {}
        for model_name, model_column in models.items():
            model_rmse = values[model_column]["rmse_m3s"]
            horizon_result.update(
                {
                    f"{model_name}_minus_{comparator}_rmse_m3s": (
                        model_rmse - values[comparator_column]["rmse_m3s"]
                    )
                    for comparator, comparator_column in comparators.items()
                    if comparator != model_name
                }
            )
        per_horizon[str(horizon)] = horizon_result
    result: dict[str, Any] = {"per_horizon": per_horizon}
    for model_name in models:
        for comparator in comparators:
            if comparator == model_name:
                continue
            deltas = [
                per_horizon[str(horizon)][f"{model_name}_minus_{comparator}_rmse_m3s"]
                for horizon in HORIZONS
            ]
            result[f"{model_name}_beats_{comparator}_all_horizons"] = all(
                delta < 0.0 for delta in deltas
            )
            result[f"{model_name}_not_worse_than_{comparator}_all_horizons"] = all(
                delta <= 0.0 for delta in deltas
            )
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
        "physical_online_expert_blend_m3s",
        "action_innovation_wwm_m3s",
        "causal_persistence_m3s",
        "target_observation_available_at_utc",
        "online_expert_matured_sample_count",
        "online_expert_raw_weight",
        "online_expert_evidence_threshold",
    }
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValueError("online_expert_traditional_source_columns_invalid")
    rows = list(reader)
    if not rows:
        raise ValueError("online_expert_traditional_source_axis_invalid")
    return rows


def _load_source_report(path: Path) -> tuple[bytes, Mapping[str, Any]]:
    body, report = cross._load_json(path)
    outputs = report.get("outputs") or {}
    claims = report.get("claim_boundary") or {}
    information = report.get("information_boundary") or {}
    if (
        report.get("schema") != blend.SCHEMA
        or report.get("status") != "physical_first_online_expert_blend_posthoc_complete"
        or claims.get("physical_online_expert_blend_posthoc_executed") is not True
        or claims.get("geospatial_kernel_validated") is not False
        or information.get("evaluation_counts_as_fresh_validation") is not False
        or not set(WINDOW_NAMES).issubset(outputs)
    ):
        raise ValueError("online_expert_traditional_source_report_invalid")
    return body, report


def _count_deltas(
    windows: Mapping[str, Mapping[str, Any]],
    *,
    model: str,
    comparator: str,
    sign: int,
) -> int:
    return sum(
        sign * values[f"{model}_minus_{comparator}_rmse_m3s"] > 0.0
        for result in windows.values()
        for values in result["comparison"]["per_horizon"].values()
    )


def _count_warmup_ablation_deltas(
    windows: Mapping[str, Mapping[str, Any]],
    *,
    candidate: str,
    comparator: str,
    sign: int,
) -> int:
    return sum(
        sign * values[f"{candidate}_minus_{comparator}_rmse_m3s"] > 0.0
        for result in windows.values()
        for values in result["warmup_ablation"]["per_horizon"].values()
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
        raise ValueError("online_expert_traditional_generated_at_invalid")
    return value.astimezone(UTC)


def _json_body(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> None:
    args = parse_args()
    paths = {name: args.output_root / f"{name}_predictions.csv" for name in WINDOW_NAMES}
    bodies, report = compile_online_expert_traditional_baselines_posthoc(
        source_report_path=args.source_report,
        prediction_paths=paths,
    )
    args.output_root.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    for name, body in bodies.items():
        paths[name].write_bytes(body)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    for name in WINDOW_NAMES:
        for horizon in HORIZONS:
            values = report["windows"][name]["comparison"]["per_horizon"][str(horizon)]
            print(
                f"window={name} horizon={horizon}h "
                f"selector_minus_raw="
                f"{values['selector_minus_raw_physical_rmse_m3s']:.6f} "
                f"selector_minus_v5="
                f"{values['selector_minus_v5_rmse_m3s']:.6f}"
            )


if __name__ == "__main__":
    main()
