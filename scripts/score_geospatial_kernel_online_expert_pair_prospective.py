#!/usr/bin/env python3
"""Score sealed prospective v5 and Follow-the-Leader campaigns once."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.online_expert_evaluation import (
    external_regret_to_best_fixed_constituent,
)
from data_agent.uwm.geospatial_kernel_v2.prospective_online_expert_pair import (
    PRIMARY_CANDIDATE_ID,
    TRADITIONAL_BASELINE_ID,
)
from scripts import update_geospatial_kernel_online_expert_pair_matured_state as updater

REPO_ROOT = Path(__file__).resolve().parents[1]
SCORER_PATH = Path(__file__).resolve()
ONLINE_EXPERT_EVALUATION_PATH = REPO_ROOT / (
    "data_agent/uwm/geospatial_kernel_v2/online_expert_evaluation.py"
)
CAMPAIGN_SCHEMA = "gwm.geospatial_kernel.online_expert_pair_campaign_index.v1"
REPORT_SCHEMA = "gwm.geospatial_kernel.online_expert_pair_prospective_score.v1"
SYSTEMS = ("center_hill", "j_percy_priest")
HORIZONS = (1, 3, 6, 12)


@dataclass(frozen=True)
class ProspectiveOnlineExpertPairScoreConfig:
    minimum_complete_case_count_per_system_horizon: int = 500
    evidence_z_threshold: float = 1.96

    def __post_init__(self) -> None:
        if (
            not isinstance(
                self.minimum_complete_case_count_per_system_horizon,
                int,
            )
            or isinstance(
                self.minimum_complete_case_count_per_system_horizon,
                bool,
            )
            or self.minimum_complete_case_count_per_system_horizon < 1
            or not math.isfinite(float(self.evidence_z_threshold))
            or self.evidence_z_threshold <= 0.0
        ):
            raise ValueError("online_expert_pair_score_config_invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "systems": list(SYSTEMS),
            "forecast_horizons_hours": list(HORIZONS),
            "primary_candidate": PRIMARY_CANDIDATE_ID,
            "traditional_baseline": TRADITIONAL_BASELINE_ID,
            "constituent_experts": [
                "physical_online_residual_adaptation_v4",
                "action_innovation_wwm",
            ],
            "primary_metric": "equal_horizon_macro_mean_mse_ratio_v5_to_selector",
            "secondary_constituent_metric": (
                "equal_horizon_macro_mean_mse_ratio_v5_to_best_fixed_"
                "constituent_expert_in_hindsight"
            ),
            "secondary_time_ordered_metric": (
                "external_squared_error_regret_to_best_fixed_constituent_expert"
            ),
            "external_regret_prefix_reference": (
                "minimum_cumulative_squared_loss_of_v4_or_wwm_at_each_prefix"
            ),
            "minimum_complete_case_count_per_system_horizon": (
                self.minimum_complete_case_count_per_system_horizon
            ),
            "paired_loss_evidence_z_threshold": self.evidence_z_threshold,
            "paired_loss_hac_maximum_lag_hours": "forecast_horizon_hours_minus_one",
            "system_compensation_allowed": False,
            "system_numerical_nonregression_threshold": ("macro_mean_mse_ratio <= 1.0"),
            "strict_improvement_required_in_at_least_one_system": True,
            "hac_supported_horizon_improvement_required": True,
            "configuration_selected_after_campaign_outcome_access": False,
        }


@dataclass(frozen=True)
class ProspectiveOnlineExpertPairScoreRecord:
    system_id: str
    forecast_id: str
    issue_time: datetime
    forecast_horizon_hours: int
    v5_prediction_m3s: float
    selector_prediction_m3s: float
    v4_prediction_m3s: float
    wwm_prediction_m3s: float
    observed_discharge_m3s: float

    def __post_init__(self) -> None:
        values = (
            self.v5_prediction_m3s,
            self.selector_prediction_m3s,
            self.v4_prediction_m3s,
            self.wwm_prediction_m3s,
            self.observed_discharge_m3s,
        )
        if (
            self.system_id not in SYSTEMS
            or not isinstance(self.forecast_id, str)
            or not self.forecast_id.strip()
            or not _aware(self.issue_time)
            or self.forecast_horizon_hours not in HORIZONS
            or any(isinstance(value, bool) for value in values)
            or any(not math.isfinite(float(value)) for value in values)
            or float(self.v5_prediction_m3s) < 0.0
            or float(self.selector_prediction_m3s) < 0.0
            or float(self.v4_prediction_m3s) < 0.0
            or float(self.wwm_prediction_m3s) < 0.0
        ):
            raise ValueError("online_expert_pair_score_record_invalid")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-index", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def compile_online_expert_pair_prospective_score(
    *,
    campaign_index_path: Path,
    config: ProspectiveOnlineExpertPairScoreConfig | None = None,
) -> dict[str, Any]:
    """Verify every sealed issue and score the fixed candidate/baseline pair."""

    fixed = config or ProspectiveOnlineExpertPairScoreConfig()
    campaign_body, campaign = updater._load_json(campaign_index_path)
    campaign_id, evaluation_time, entries_by_system = _validate_campaign(campaign)
    records: list[ProspectiveOnlineExpertPairScoreRecord] = []
    issue_count_by_system: dict[str, int] = {}
    observation_sources: dict[str, set[str]] = {system: set() for system in SYSTEMS}
    seen_forecasts: set[tuple[str, str]] = set()
    for system in SYSTEMS:
        seen_issues: set[datetime] = set()
        for entry in entries_by_system[system]:
            run_report_path, _ = updater._read_verified_descriptor(entry["prediction_run_report"])
            observation_path, _ = updater._read_verified_descriptor(
                entry["authoritative_observations"]
            )
            _, run_report, prediction, _ = updater._recompute_prediction_run(run_report_path)
            _, observation_payload = updater._load_json(observation_path)
            observations, _, source_id = updater._validate_observations(
                observation_payload,
                expected_system_id=system,
                update_time=evaluation_time,
            )
            feedbacks = updater._feedbacks_from_predictions(
                prediction,
                observations,
                expected_system_id=system,
            )
            if len(feedbacks) != len(HORIZONS):
                raise ValueError("online_expert_pair_score_incomplete_issue_outcomes")
            issue_time = _parse_datetime(run_report["issue_time_utc"])
            if issue_time in seen_issues:
                raise ValueError("online_expert_pair_score_duplicate_issue")
            seen_issues.add(issue_time)
            observation_by_target = {
                value["target_support_end"]: value["observed_discharge_m3s"]
                for value in observations
            }
            for row in prediction["predictions"]:
                forecast_id = row["forecast_id"]
                identity = (system, forecast_id)
                if identity in seen_forecasts:
                    raise ValueError("online_expert_pair_score_duplicate_forecast")
                seen_forecasts.add(identity)
                target = _parse_datetime(row["target_support_end_utc"])
                if target not in observation_by_target:
                    raise ValueError("online_expert_pair_score_observation_axis_mismatch")
                records.append(
                    ProspectiveOnlineExpertPairScoreRecord(
                        system_id=system,
                        forecast_id=forecast_id,
                        issue_time=issue_time,
                        forecast_horizon_hours=row["forecast_horizon_hours"],
                        v5_prediction_m3s=row["physical_online_expert_blend_v5_m3s"],
                        selector_prediction_m3s=row["evidence_gated_follow_the_leader_m3s"],
                        v4_prediction_m3s=row["physical_online_residual_adaptation_v4_m3s"],
                        wwm_prediction_m3s=row["action_innovation_wwm_m3s"],
                        observed_discharge_m3s=observation_by_target[target],
                    )
                )
            observation_sources[system].add(source_id)
        issue_count_by_system[system] = len(seen_issues)
    scoring = score_online_expert_pair_records(records, config=fixed)
    gate = scoring["prospective_incremental_value_gate"]
    return {
        "schema": REPORT_SCHEMA,
        "status": (
            "prospective_online_expert_pair_score_complete"
            if gate["minimum_coverage_passed"]
            else "prospective_online_expert_pair_score_insufficient_coverage"
        ),
        "campaign_id": campaign_id,
        "evaluated_at": evaluation_time.astimezone(UTC).isoformat(),
        "scoring_lock": fixed.as_dict(),
        "source_artifacts": {
            "campaign_index": _artifact(campaign_index_path, campaign_body),
        },
        "implementation_artifacts": {
            "prospective_pair_scorer": _artifact(
                SCORER_PATH,
                SCORER_PATH.read_bytes(),
            ),
            "online_expert_evaluation": _artifact(
                ONLINE_EXPERT_EVALUATION_PATH,
                ONLINE_EXPERT_EVALUATION_PATH.read_bytes(),
            ),
        },
        "execution": {
            "issue_count_by_system": issue_count_by_system,
            "prediction_record_count": len(records),
            "observation_source_ids_by_system": {
                system: sorted(values) for system, values in observation_sources.items()
            },
            "every_prediction_run_recomputed_exactly": True,
            "all_observations_authoritative_approved_and_unimputed": True,
            "scores_written_back_to_predictions_or_online_state": False,
        },
        **scoring,
        "claim_boundary": {
            "campaign_index_present_and_artifacts_verified": True,
            "external_prospective_timestamp_verified": False,
            "minimum_coverage_passed": gate["minimum_coverage_passed"],
            "bounded_incremental_value_over_traditional_selector_supported": gate["passed"],
            "v5_beats_best_fixed_constituent_expert_diagnostic": scoring[
                "best_fixed_constituent_expert_diagnostic"
            ]["passed"],
            "constituent_expert_diagnostic_is_primary_promotion_gate": False,
            "v5_lower_external_regret_than_traditional_selector_diagnostic": scoring[
                "external_regret_diagnostic"
            ]["passed"],
            "external_regret_diagnostic_is_primary_promotion_gate": False,
            "broad_model_superiority_supported": False,
            "operational_superiority_validated": False,
            "geospatial_kernel_validated": False,
            "runtime_default_enabled": False,
        },
    }


def score_online_expert_pair_records(
    records: list[ProspectiveOnlineExpertPairScoreRecord],
    *,
    config: ProspectiveOnlineExpertPairScoreConfig | None = None,
) -> dict[str, Any]:
    fixed = config or ProspectiveOnlineExpertPairScoreConfig()
    grouped: dict[str, dict[int, list[ProspectiveOnlineExpertPairScoreRecord]]] = {
        system: {horizon: [] for horizon in HORIZONS} for system in SYSTEMS
    }
    identities: set[tuple[str, str]] = set()
    for record in records:
        if not isinstance(record, ProspectiveOnlineExpertPairScoreRecord):
            raise ValueError("online_expert_pair_score_record_invalid")
        identity = (record.system_id, record.forecast_id)
        if identity in identities:
            raise ValueError("online_expert_pair_score_duplicate_forecast")
        identities.add(identity)
        grouped[record.system_id][record.forecast_horizon_hours].append(record)
    systems: dict[str, Any] = {}
    minimum_passed = True
    for system in SYSTEMS:
        horizons: dict[str, Any] = {}
        mse_ratios: list[float] = []
        best_fixed_expert_mse_ratios: list[float] = []
        v5_final_average_external_regrets: list[float] = []
        selector_final_average_external_regrets: list[float] = []
        coverage_passed = True
        system_hac_supported = False
        for horizon in HORIZONS:
            values = sorted(
                grouped[system][horizon],
                key=lambda value: (value.issue_time, value.forecast_id),
            )
            result = _score_horizon(values, horizon=horizon, config=fixed)
            horizons[str(horizon)] = result
            coverage_passed = coverage_passed and result["minimum_complete_case_count_passed"]
            ratio = result["v5_to_selector_mse_ratio"]
            if ratio is not None:
                mse_ratios.append(ratio)
            fixed_ratio = result["v5_to_best_fixed_constituent_expert_mse_ratio"]
            if fixed_ratio is not None:
                best_fixed_expert_mse_ratios.append(fixed_ratio)
            v5_regret = result["v5_external_regret_to_best_fixed_constituent"][
                "final_average_per_case_m6s2"
            ]
            if v5_regret is not None:
                v5_final_average_external_regrets.append(v5_regret)
            selector_regret = result["selector_external_regret_to_best_fixed_constituent"][
                "final_average_per_case_m6s2"
            ]
            if selector_regret is not None:
                selector_final_average_external_regrets.append(selector_regret)
            system_hac_supported = (
                system_hac_supported or result["paired_improvement_exceeds_hac_threshold"]
            )
        macro_ratio = sum(mse_ratios) / len(HORIZONS) if len(mse_ratios) == len(HORIZONS) else None
        best_fixed_macro_ratio = (
            sum(best_fixed_expert_mse_ratios) / len(HORIZONS)
            if len(best_fixed_expert_mse_ratios) == len(HORIZONS)
            else None
        )
        v5_macro_external_regret = (
            sum(v5_final_average_external_regrets) / len(HORIZONS)
            if len(v5_final_average_external_regrets) == len(HORIZONS)
            else None
        )
        selector_macro_external_regret = (
            sum(selector_final_average_external_regrets) / len(HORIZONS)
            if len(selector_final_average_external_regrets) == len(HORIZONS)
            else None
        )
        not_worse = coverage_passed and macro_ratio is not None and macro_ratio <= 1.0
        strict = coverage_passed and macro_ratio is not None and macro_ratio < 1.0
        systems[system] = {
            "horizons": horizons,
            "minimum_coverage_passed": coverage_passed,
            "equal_horizon_macro_mean_mse_ratio_v5_to_selector": macro_ratio,
            "v5_not_worse_numerically_without_cross_system_compensation": (not_worse),
            "v5_strictly_improves_selector_macro_mse": strict,
            "has_hac_supported_horizon_improvement": system_hac_supported,
            "equal_horizon_macro_mean_mse_ratio_v5_to_best_fixed_constituent_expert": (
                best_fixed_macro_ratio
            ),
            "v5_not_worse_numerically_than_best_fixed_constituent_expert": (
                coverage_passed
                and best_fixed_macro_ratio is not None
                and best_fixed_macro_ratio <= 1.0
            ),
            "v5_strictly_improves_best_fixed_constituent_expert_macro_mse": (
                coverage_passed
                and best_fixed_macro_ratio is not None
                and best_fixed_macro_ratio < 1.0
            ),
            "equal_horizon_macro_mean_final_average_external_regret_m6s2": {
                "v5": v5_macro_external_regret,
                "selector": selector_macro_external_regret,
            },
            "v5_external_regret_not_higher_than_selector": (
                coverage_passed
                and v5_macro_external_regret is not None
                and selector_macro_external_regret is not None
                and v5_macro_external_regret <= selector_macro_external_regret
            ),
            "v5_external_regret_strictly_lower_than_selector": (
                coverage_passed
                and v5_macro_external_regret is not None
                and selector_macro_external_regret is not None
                and v5_macro_external_regret < selector_macro_external_regret
            ),
        }
        minimum_passed = minimum_passed and coverage_passed
    all_systems_not_worse = minimum_passed and all(
        systems[system]["v5_not_worse_numerically_without_cross_system_compensation"]
        for system in SYSTEMS
    )
    at_least_one_strict = minimum_passed and any(
        systems[system]["v5_strictly_improves_selector_macro_mse"] for system in SYSTEMS
    )
    strict_system_hac_supported = minimum_passed and any(
        systems[system]["v5_strictly_improves_selector_macro_mse"]
        and systems[system]["has_hac_supported_horizon_improvement"]
        for system in SYSTEMS
    )
    passed = (
        minimum_passed
        and all_systems_not_worse
        and at_least_one_strict
        and strict_system_hac_supported
    )
    all_systems_not_worse_than_best_fixed = minimum_passed and all(
        systems[system]["v5_not_worse_numerically_than_best_fixed_constituent_expert"]
        for system in SYSTEMS
    )
    at_least_one_system_beats_best_fixed = minimum_passed and any(
        systems[system]["v5_strictly_improves_best_fixed_constituent_expert_macro_mse"]
        for system in SYSTEMS
    )
    all_systems_v5_regret_not_higher = minimum_passed and all(
        systems[system]["v5_external_regret_not_higher_than_selector"] for system in SYSTEMS
    )
    at_least_one_system_v5_regret_lower = minimum_passed and any(
        systems[system]["v5_external_regret_strictly_lower_than_selector"] for system in SYSTEMS
    )
    return {
        "systems": systems,
        "prospective_incremental_value_gate": {
            "minimum_coverage_passed": minimum_passed,
            "both_systems_not_worse_numerically_without_compensation": (all_systems_not_worse),
            "at_least_one_system_strictly_improved": at_least_one_strict,
            "strictly_improved_system_has_hac_supported_horizon": (strict_system_hac_supported),
            "passed": passed,
        },
        "best_fixed_constituent_expert_diagnostic": {
            "comparison_selected_after_outcome_access": True,
            "comparison_role": "secondary_harder_diagnostic_not_primary_gate",
            "both_systems_not_worse_numerically": (all_systems_not_worse_than_best_fixed),
            "at_least_one_system_strictly_improved": (at_least_one_system_beats_best_fixed),
            "passed": (
                all_systems_not_worse_than_best_fixed and at_least_one_system_beats_best_fixed
            ),
        },
        "external_regret_diagnostic": {
            "best_fixed_comparator_selected_after_outcome_access": True,
            "comparison_role": "secondary_time_ordered_diagnostic_not_primary_gate",
            "both_systems_v5_regret_not_higher_than_selector": (all_systems_v5_regret_not_higher),
            "at_least_one_system_v5_regret_strictly_lower_than_selector": (
                at_least_one_system_v5_regret_lower
            ),
            "passed": (all_systems_v5_regret_not_higher and at_least_one_system_v5_regret_lower),
        },
    }


def _score_horizon(
    records: list[ProspectiveOnlineExpertPairScoreRecord],
    *,
    horizon: int,
    config: ProspectiveOnlineExpertPairScoreConfig,
) -> dict[str, object]:
    count = len(records)
    observed = [float(value.observed_discharge_m3s) for value in records]
    v5 = [float(value.v5_prediction_m3s) for value in records]
    selector = [float(value.selector_prediction_m3s) for value in records]
    v4 = [float(value.v4_prediction_m3s) for value in records]
    wwm = [float(value.wwm_prediction_m3s) for value in records]
    v5_errors = [prediction - target for prediction, target in zip(v5, observed, strict=True)]
    selector_errors = [
        prediction - target for prediction, target in zip(selector, observed, strict=True)
    ]
    v4_errors = [prediction - target for prediction, target in zip(v4, observed, strict=True)]
    wwm_errors = [prediction - target for prediction, target in zip(wwm, observed, strict=True)]
    v5_mse = sum(value**2 for value in v5_errors) / count if count else None
    selector_mse = sum(value**2 for value in selector_errors) / count if count else None
    v4_mse = sum(value**2 for value in v4_errors) / count if count else None
    wwm_mse = sum(value**2 for value in wwm_errors) / count if count else None
    v5_external_regret = external_regret_to_best_fixed_constituent(
        algorithm_errors=v5_errors,
        v4_errors=v4_errors,
        wwm_errors=wwm_errors,
    )
    selector_external_regret = external_regret_to_best_fixed_constituent(
        algorithm_errors=selector_errors,
        v4_errors=v4_errors,
        wwm_errors=wwm_errors,
    )
    ratio: float | None = None
    if v5_mse is not None and selector_mse is not None:
        if selector_mse > 0.0:
            ratio = v5_mse / selector_mse
        elif v5_mse == 0.0:
            ratio = 1.0
    best_fixed_expert: str | None = None
    best_fixed_mse: float | None = None
    best_fixed_ratio: float | None = None
    if v4_mse is not None and wwm_mse is not None and v5_mse is not None:
        if v4_mse < wwm_mse:
            best_fixed_expert = "physical_online_residual_adaptation_v4"
            best_fixed_mse = v4_mse
        elif wwm_mse < v4_mse:
            best_fixed_expert = "action_innovation_wwm"
            best_fixed_mse = wwm_mse
        else:
            best_fixed_expert = "tie"
            best_fixed_mse = v4_mse
        if best_fixed_mse > 0.0:
            best_fixed_ratio = v5_mse / best_fixed_mse
        elif v5_mse == 0.0:
            best_fixed_ratio = 1.0
    improvements_by_issue = {
        value.issue_time: selector_error**2 - v5_error**2
        for value, selector_error, v5_error in zip(
            records,
            selector_errors,
            v5_errors,
            strict=True,
        )
    }
    if len(improvements_by_issue) != count:
        raise ValueError("online_expert_pair_score_duplicate_issue_horizon")
    paired = _hac_paired_improvement(
        improvements_by_issue,
        maximum_lag_hours=horizon - 1,
        evidence_z_threshold=config.evidence_z_threshold,
    )
    return {
        "complete_case_count": count,
        "minimum_complete_case_count_passed": (
            count >= config.minimum_complete_case_count_per_system_horizon
        ),
        "prediction_difference_count": sum(
            left != right for left, right in zip(v5, selector, strict=True)
        ),
        "v5": _metrics(v5_errors),
        "selector": _metrics(selector_errors),
        "v4": _metrics(v4_errors),
        "wwm": _metrics(wwm_errors),
        "v5_minus_selector_rmse_m3s": (
            None
            if v5_mse is None or selector_mse is None
            else math.sqrt(v5_mse) - math.sqrt(selector_mse)
        ),
        "v5_to_selector_mse_ratio": ratio,
        "v5_minus_v4_rmse_m3s": (
            None if v5_mse is None or v4_mse is None else math.sqrt(v5_mse) - math.sqrt(v4_mse)
        ),
        "v5_minus_wwm_rmse_m3s": (
            None if v5_mse is None or wwm_mse is None else math.sqrt(v5_mse) - math.sqrt(wwm_mse)
        ),
        "best_fixed_constituent_expert_in_hindsight": best_fixed_expert,
        "v5_to_best_fixed_constituent_expert_mse_ratio": best_fixed_ratio,
        "v5_external_regret_to_best_fixed_constituent": v5_external_regret,
        "selector_external_regret_to_best_fixed_constituent": (selector_external_regret),
        "v5_minus_selector_final_cumulative_squared_error_m6s2": (
            None if v5_mse is None or selector_mse is None else count * (v5_mse - selector_mse)
        ),
        **paired,
    }


def _metrics(errors: list[float]) -> dict[str, float | None]:
    if not errors:
        return {"rmse_m3s": None, "mae_m3s": None, "bias_m3s": None}
    count = len(errors)
    return {
        "rmse_m3s": math.sqrt(sum(value**2 for value in errors) / count),
        "mae_m3s": sum(abs(value) for value in errors) / count,
        "bias_m3s": sum(errors) / count,
    }


def _hac_paired_improvement(
    improvements_by_issue: Mapping[datetime, float],
    *,
    maximum_lag_hours: int,
    evidence_z_threshold: float,
) -> dict[str, float | bool | None]:
    count = len(improvements_by_issue)
    if not count:
        return {
            "selector_minus_v5_mean_squared_error_m6s2": None,
            "paired_improvement_hac_standard_error_m6s2": None,
            "paired_improvement_hac_threshold_m6s2": None,
            "paired_improvement_hac_z": None,
            "paired_improvement_exceeds_hac_threshold": False,
        }
    mean = sum(improvements_by_issue.values()) / count
    centered = {issue_time: value - mean for issue_time, value in improvements_by_issue.items()}
    long_run_variance = sum(value**2 for value in centered.values()) / count
    for lag in range(1, maximum_lag_hours + 1):
        autocovariance = (
            sum(
                value * centered[issue_time - timedelta(hours=lag)]
                for issue_time, value in centered.items()
                if issue_time - timedelta(hours=lag) in centered
            )
            / count
        )
        weight = 1.0 - lag / (maximum_lag_hours + 1)
        long_run_variance += 2.0 * weight * autocovariance
    standard_error = math.sqrt(max(0.0, long_run_variance) / count)
    threshold = evidence_z_threshold * standard_error
    z_value = mean / standard_error if standard_error > 0.0 else None
    return {
        "selector_minus_v5_mean_squared_error_m6s2": mean,
        "paired_improvement_hac_standard_error_m6s2": standard_error,
        "paired_improvement_hac_threshold_m6s2": threshold,
        "paired_improvement_hac_z": z_value,
        "paired_improvement_exceeds_hac_threshold": mean > threshold,
    }


def _validate_campaign(
    payload: Mapping[str, object],
) -> tuple[str, datetime, Mapping[str, list[Mapping[str, object]]]]:
    if set(payload) != {
        "schema",
        "campaign_id",
        "evaluation_time_utc",
        "expected_systems",
        "systems",
        "values_imputed",
    }:
        raise ValueError("online_expert_pair_campaign_invalid")
    campaign_id = payload.get("campaign_id")
    systems = payload.get("systems")
    if (
        payload.get("schema") != CAMPAIGN_SCHEMA
        or not isinstance(campaign_id, str)
        or not campaign_id.strip()
        or payload.get("expected_systems") != list(SYSTEMS)
        or not isinstance(systems, Mapping)
        or set(systems) != set(SYSTEMS)
        or payload.get("values_imputed") is not False
    ):
        raise ValueError("online_expert_pair_campaign_invalid")
    entries: dict[str, list[Mapping[str, object]]] = {}
    for system in SYSTEMS:
        values = systems[system]
        if not isinstance(values, list) or not values:
            raise ValueError("online_expert_pair_campaign_axis_invalid")
        parsed = []
        for value in values:
            if not isinstance(value, Mapping) or set(value) != {
                "prediction_run_report",
                "authoritative_observations",
            }:
                raise ValueError("online_expert_pair_campaign_entry_invalid")
            parsed.append(value)
        entries[system] = parsed
    return (
        campaign_id,
        _parse_datetime(payload["evaluation_time_utc"]),
        entries,
    )


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    try:
        display = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        display = str(path.resolve())
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("online_expert_pair_score_datetime_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("online_expert_pair_score_datetime_invalid") from exc
    if not _aware(parsed):
        raise ValueError("online_expert_pair_score_datetime_invalid")
    return parsed.astimezone(UTC)


def _aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() is not None


def _json_body(payload: Mapping[str, object]) -> bytes:
    return (json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> None:
    args = parse_args()
    report = compile_online_expert_pair_prospective_score(
        campaign_index_path=args.campaign_index,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    print(
        "prospective_incremental_value_gate_passed="
        f"{report['prospective_incremental_value_gate']['passed']}"
    )


if __name__ == "__main__":
    main()
