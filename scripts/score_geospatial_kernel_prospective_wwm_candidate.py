#!/usr/bin/env python3
"""Score a sealed integrated WWM campaign with the frozen go/no-go gate."""

from __future__ import annotations

import argparse
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts import update_geospatial_kernel_online_expert_pair_matured_state as pair_updater
from scripts.run_geospatial_kernel_prospective_wwm_candidate_outcome_free import (
    _artifact,
    _json_body,
    _load_json,
    _parse_datetime,
)
from scripts.score_geospatial_kernel_online_expert_pair_prospective import (
    HORIZONS,
    SYSTEMS,
    ProspectiveOnlineExpertPairScoreConfig,
    ProspectiveOnlineExpertPairScoreRecord,
    _hac_paired_improvement,
    _metrics,
    score_online_expert_pair_records,
)
from scripts.update_geospatial_kernel_prospective_wwm_candidate_state import (
    _read_verified_descriptor,
    _recompute_prediction_run,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCORER_PATH = Path(__file__).resolve()
SELECTOR_SCORER_PATH = REPO_ROOT / (
    "scripts/score_geospatial_kernel_online_expert_pair_prospective.py"
)
CAMPAIGN_SCHEMA = "gwm.geospatial_kernel.prospective_wwm_candidate_campaign.v1"
REPORT_SCHEMA = "gwm.geospatial_kernel.prospective_wwm_candidate_score.v2"


@dataclass(frozen=True)
class StrongBaselineScoreRecord:
    system_id: str
    forecast_id: str
    issue_time: datetime
    forecast_horizon_hours: int
    v5_prediction_m3s: float
    raw_physical_m3s: float
    causal_persistence_m3s: float
    classical_arx_m3s: float
    observed_discharge_m3s: float

    def __post_init__(self) -> None:
        values = (
            self.v5_prediction_m3s,
            self.raw_physical_m3s,
            self.causal_persistence_m3s,
            self.classical_arx_m3s,
            self.observed_discharge_m3s,
        )
        if (
            self.system_id not in SYSTEMS
            or not isinstance(self.forecast_id, str)
            or not self.forecast_id.strip()
            or self.issue_time.tzinfo is None
            or self.issue_time.utcoffset() is None
            or self.forecast_horizon_hours not in HORIZONS
            or any(isinstance(value, bool) for value in values)
            or any(not math.isfinite(float(value)) for value in values)
            or any(float(value) < 0.0 for value in values)
        ):
            raise ValueError("prospective_wwm_candidate_strong_baseline_record_invalid")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-index", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    return parser.parse_args()


def compile_prospective_wwm_candidate_score(
    *,
    campaign_index_path: Path,
    config: ProspectiveOnlineExpertPairScoreConfig | None = None,
) -> dict[str, Any]:
    """Recompute all prediction runs and score only complete joined outcomes."""

    fixed = config or ProspectiveOnlineExpertPairScoreConfig()
    campaign_body, campaign = _load_json(campaign_index_path)
    campaign_id, evaluation_time, entries_by_system = _validate_campaign(campaign)
    records: list[ProspectiveOnlineExpertPairScoreRecord] = []
    strong_records: list[StrongBaselineScoreRecord] = []
    issue_count_by_system: dict[str, int] = {}
    observation_sources: dict[str, set[str]] = {
        system: set() for system in SYSTEMS
    }
    seen_forecasts: set[tuple[str, str]] = set()
    for system in SYSTEMS:
        seen_issues = set()
        for entry in entries_by_system[system]:
            run_report_path, _ = _read_verified_descriptor(
                entry["prediction_run_report"]
            )
            observation_path, _ = _read_verified_descriptor(
                entry["authoritative_observations"]
            )
            _, _, _, predictions, output_rows = _recompute_prediction_run(
                run_report_path
            )
            output_by_forecast = {
                row.get("forecast_id"): row for row in output_rows
            }
            if (
                len(output_by_forecast) != len(output_rows)
                or set(output_by_forecast)
                != {prediction.forecast_id for prediction in predictions}
            ):
                raise ValueError(
                    "prospective_wwm_candidate_score_prediction_axis_invalid"
                )
            _, observation_payload = _load_json(observation_path)
            observations, _, source_id = pair_updater._validate_observations(
                observation_payload,
                expected_system_id=system,
                update_time=evaluation_time,
            )
            observed_by_target = {
                value["target_support_end"]: value["observed_discharge_m3s"]
                for value in observations
            }
            if len(predictions) != len(HORIZONS) or set(observed_by_target) != {
                value.target_support_end for value in predictions
            }:
                raise ValueError("prospective_wwm_candidate_score_incomplete_issue")
            issue_time = predictions[0].expert_pair_step.issue_time
            if issue_time in seen_issues:
                raise ValueError("prospective_wwm_candidate_score_duplicate_issue")
            seen_issues.add(issue_time)
            for prediction in predictions:
                identity = (system, prediction.forecast_id)
                if identity in seen_forecasts:
                    raise ValueError(
                        "prospective_wwm_candidate_score_duplicate_forecast"
                    )
                seen_forecasts.add(identity)
                pair = prediction.expert_pair_step
                candidate = pair.primary_candidate
                output_row = output_by_forecast[prediction.forecast_id]
                observed = observed_by_target[prediction.target_support_end]
                records.append(
                    ProspectiveOnlineExpertPairScoreRecord(
                        system_id=system,
                        forecast_id=prediction.forecast_id,
                        issue_time=issue_time,
                        forecast_horizon_hours=(
                            prediction.v4_step.forecast_horizon_hours
                        ),
                        v5_prediction_m3s=candidate.blended_prediction_m3s,
                        selector_prediction_m3s=(
                            pair.traditional_baseline.selected_prediction_m3s
                        ),
                        v4_prediction_m3s=(
                            prediction.v4_step.corrected_prediction_m3s
                        ),
                        wwm_prediction_m3s=candidate.alternative_prediction_m3s,
                        observed_discharge_m3s=observed,
                    )
                )
                try:
                    strong_records.append(
                        StrongBaselineScoreRecord(
                            system_id=system,
                            forecast_id=prediction.forecast_id,
                            issue_time=issue_time,
                            forecast_horizon_hours=(
                                prediction.v4_step.forecast_horizon_hours
                            ),
                            v5_prediction_m3s=(
                                candidate.blended_prediction_m3s
                            ),
                            raw_physical_m3s=float(
                                output_row["physical_open_loop_m3s"]
                            ),
                            causal_persistence_m3s=float(
                                output_row["causal_persistence_m3s"]
                            ),
                            classical_arx_m3s=float(
                                output_row["classical_arx_m3s"]
                            ),
                            observed_discharge_m3s=observed,
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "prospective_wwm_candidate_score_strong_baseline_invalid"
                    ) from exc
            observation_sources[system].add(source_id)
        issue_count_by_system[system] = len(seen_issues)
    selector_scoring = score_online_expert_pair_records(records, config=fixed)
    selector_gate = selector_scoring["prospective_incremental_value_gate"]
    strong_scoring = _score_strong_baselines(strong_records, config=fixed)
    strong_gate = strong_scoring["gate"]
    minimum_coverage_passed = bool(
        selector_gate["minimum_coverage_passed"]
        and strong_gate["minimum_coverage_passed"]
    )
    gate = {
        "minimum_coverage_passed": minimum_coverage_passed,
        "selector_incremental_value_gate_passed": selector_gate["passed"],
        "all_system_horizon_strong_baseline_nonregression_passed": (
            strong_gate[
                "all_system_horizon_strong_baseline_nonregression_passed"
            ]
        ),
        "every_system_has_hac_supported_improvement_over_best_strong_baseline": (
            strong_gate[
                "every_system_has_hac_supported_improvement_over_best_strong_baseline"
            ]
        ),
        "passed": bool(
            minimum_coverage_passed
            and selector_gate["passed"]
            and strong_gate["passed"]
        ),
    }
    scoring_without_selector_gate = {
        key: value
        for key, value in selector_scoring.items()
        if key != "prospective_incremental_value_gate"
    }
    return {
        "schema": REPORT_SCHEMA,
        "status": (
            "prospective_wwm_candidate_score_complete"
            if gate["minimum_coverage_passed"]
            else "prospective_wwm_candidate_score_insufficient_coverage"
        ),
        "campaign_id": campaign_id,
        "evaluated_at_utc": evaluation_time.isoformat(),
        "scoring_lock": {
            **fixed.as_dict(),
            "strong_traditional_baselines": [
                "raw_physical_open_loop",
                "causal_persistence",
                "classical_causal_arx_locked_zero_refit",
            ],
            "strong_baseline_nonregression_required_for_every_system_horizon": True,
            "hac_improvement_over_best_strong_baseline_required_per_system": True,
            "selector_gate_also_required": True,
        },
        "source_artifacts": {
            "campaign_index": _artifact(campaign_index_path, campaign_body),
        },
        "implementation_artifacts": {
            "integrated_campaign_scorer": _artifact(
                SCORER_PATH,
                SCORER_PATH.read_bytes(),
            ),
            "selector_and_hac_scorer": _artifact(
                SELECTOR_SCORER_PATH,
                SELECTOR_SCORER_PATH.read_bytes(),
            ),
        },
        "execution": {
            "issue_count_by_system": issue_count_by_system,
            "prediction_record_count": len(records),
            "every_prediction_run_recomputed_exactly": True,
            "all_observations_authoritative_approved_and_unimputed": True,
            "v4_predictions_generated_inside_sealed_runtime": True,
            "persistence_and_arx_predictions_generated_inside_sealed_runtime": True,
            "observation_source_ids_by_system": {
                system: sorted(values)
                for system, values in observation_sources.items()
            },
        },
        **scoring_without_selector_gate,
        "selector_incremental_value_gate": selector_gate,
        "strong_traditional_baseline_comparison": strong_scoring,
        "prospective_incremental_value_gate": gate,
        "claim_boundary": {
            "minimum_coverage_passed": gate["minimum_coverage_passed"],
            "bounded_incremental_value_over_traditional_selector_supported": (
                selector_gate["passed"]
            ),
            "strong_traditional_baseline_gate_passed": strong_gate["passed"],
            "integrated_promotion_gate_passed": gate["passed"],
            "external_prospective_timestamp_verified": False,
            "broad_model_superiority_supported": False,
            "operational_superiority_validated": False,
            "geospatial_kernel_validated": False,
            "runtime_default_enabled": False,
        },
    }


def _score_strong_baselines(
    records: list[StrongBaselineScoreRecord],
    *,
    config: ProspectiveOnlineExpertPairScoreConfig,
) -> dict[str, Any]:
    grouped: dict[str, dict[int, list[StrongBaselineScoreRecord]]] = {
        system: {horizon: [] for horizon in HORIZONS} for system in SYSTEMS
    }
    identities: set[tuple[str, str]] = set()
    for record in records:
        if not isinstance(record, StrongBaselineScoreRecord):
            raise ValueError(
                "prospective_wwm_candidate_strong_baseline_record_invalid"
            )
        identity = (record.system_id, record.forecast_id)
        if identity in identities:
            raise ValueError("prospective_wwm_candidate_score_duplicate_forecast")
        identities.add(identity)
        grouped[record.system_id][record.forecast_horizon_hours].append(record)

    systems: dict[str, Any] = {}
    minimum_coverage_passed = True
    for system in SYSTEMS:
        horizons: dict[str, Any] = {}
        all_horizons_nonregression = True
        has_hac_improvement = False
        for horizon in HORIZONS:
            values = sorted(
                grouped[system][horizon],
                key=lambda value: (value.issue_time, value.forecast_id),
            )
            result = _score_strong_baseline_horizon(
                values,
                horizon=horizon,
                config=config,
            )
            horizons[str(horizon)] = result
            minimum_coverage_passed = bool(
                minimum_coverage_passed
                and result["minimum_complete_case_count_passed"]
            )
            all_horizons_nonregression = bool(
                all_horizons_nonregression
                and result["v5_not_worse_than_every_strong_baseline"]
            )
            has_hac_improvement = bool(
                has_hac_improvement
                or result[
                    "best_strong_baseline_improvement_exceeds_hac_threshold"
                ]
            )
        systems[system] = {
            "horizons": horizons,
            "all_horizons_not_worse_than_every_strong_baseline": (
                all_horizons_nonregression
            ),
            "has_hac_supported_horizon_improvement_over_best_strong_baseline": (
                has_hac_improvement
            ),
        }
    all_nonregression = bool(
        minimum_coverage_passed
        and all(
            systems[system][
                "all_horizons_not_worse_than_every_strong_baseline"
            ]
            for system in SYSTEMS
        )
    )
    every_system_hac = bool(
        minimum_coverage_passed
        and all(
            systems[system][
                "has_hac_supported_horizon_improvement_over_best_strong_baseline"
            ]
            for system in SYSTEMS
        )
    )
    return {
        "systems": systems,
        "gate": {
            "minimum_coverage_passed": minimum_coverage_passed,
            "all_system_horizon_strong_baseline_nonregression_passed": (
                all_nonregression
            ),
            "every_system_has_hac_supported_improvement_over_best_strong_baseline": (
                every_system_hac
            ),
            "passed": bool(all_nonregression and every_system_hac),
        },
    }


def _score_strong_baseline_horizon(
    records: list[StrongBaselineScoreRecord],
    *,
    horizon: int,
    config: ProspectiveOnlineExpertPairScoreConfig,
) -> dict[str, object]:
    count = len(records)
    observed = [float(value.observed_discharge_m3s) for value in records]
    predictions = {
        "v5": [float(value.v5_prediction_m3s) for value in records],
        "raw_physical": [float(value.raw_physical_m3s) for value in records],
        "causal_persistence": [
            float(value.causal_persistence_m3s) for value in records
        ],
        "classical_arx": [float(value.classical_arx_m3s) for value in records],
    }
    errors = {
        key: [
            prediction - target
            for prediction, target in zip(values, observed, strict=True)
        ]
        for key, values in predictions.items()
    }
    mse = {
        key: (
            sum(value**2 for value in values) / count if count else None
        )
        for key, values in errors.items()
    }
    baseline_names = ("raw_physical", "causal_persistence", "classical_arx")
    ratios = {
        name: _mse_ratio(mse["v5"], mse[name]) for name in baseline_names
    }
    best_name: str | None = None
    if count:
        best_name = min(
            baseline_names,
            key=lambda name: float(mse[name]),
        )
    improvements_by_issue: dict[datetime, float] = {}
    if best_name is not None:
        improvements_by_issue = {
            value.issue_time: baseline_error**2 - v5_error**2
            for value, baseline_error, v5_error in zip(
                records,
                errors[best_name],
                errors["v5"],
                strict=True,
            )
        }
        if len(improvements_by_issue) != count:
            raise ValueError(
                "prospective_wwm_candidate_score_duplicate_issue_horizon"
            )
    paired = _hac_paired_improvement(
        improvements_by_issue,
        maximum_lag_hours=horizon - 1,
        evidence_z_threshold=config.evidence_z_threshold,
    )
    coverage = count >= config.minimum_complete_case_count_per_system_horizon
    not_worse = bool(
        coverage
        and mse["v5"] is not None
        and all(
            mse[name] is not None and float(mse["v5"]) <= float(mse[name])
            for name in baseline_names
        )
    )
    return {
        "complete_case_count": count,
        "minimum_complete_case_count_passed": coverage,
        "metrics": {key: _metrics(value) for key, value in errors.items()},
        "v5_to_baseline_mse_ratio": ratios,
        "v5_not_worse_than_every_strong_baseline": not_worse,
        "best_strong_baseline_in_hindsight": best_name,
        "best_strong_baseline_minus_v5_mean_squared_error_m6s2": paired[
            "selector_minus_v5_mean_squared_error_m6s2"
        ],
        "best_strong_baseline_improvement_hac_standard_error_m6s2": paired[
            "paired_improvement_hac_standard_error_m6s2"
        ],
        "best_strong_baseline_improvement_hac_threshold_m6s2": paired[
            "paired_improvement_hac_threshold_m6s2"
        ],
        "best_strong_baseline_improvement_hac_z": paired[
            "paired_improvement_hac_z"
        ],
        "best_strong_baseline_improvement_exceeds_hac_threshold": paired[
            "paired_improvement_exceeds_hac_threshold"
        ],
    }


def _mse_ratio(candidate_mse: object, baseline_mse: object) -> float | None:
    if not isinstance(candidate_mse, (int, float)) or not isinstance(
        baseline_mse, (int, float)
    ):
        return None
    if baseline_mse > 0.0:
        return float(candidate_mse) / float(baseline_mse)
    if candidate_mse == 0.0:
        return 1.0
    return None


def _validate_campaign(
    payload: Mapping[str, object],
) -> tuple[str, Any, dict[str, list[Mapping[str, object]]]]:
    if set(payload) != {
        "schema",
        "campaign_id",
        "evaluation_time_utc",
        "expected_systems",
        "systems",
        "values_imputed",
    }:
        raise ValueError("prospective_wwm_candidate_campaign_invalid")
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
        raise ValueError("prospective_wwm_candidate_campaign_invalid")
    entries = {}
    for system in SYSTEMS:
        raw_entries = systems[system]
        if not isinstance(raw_entries, list) or not raw_entries:
            raise ValueError("prospective_wwm_candidate_campaign_axis_invalid")
        parsed = []
        for entry in raw_entries:
            if not isinstance(entry, Mapping) or set(entry) != {
                "prediction_run_report",
                "authoritative_observations",
            }:
                raise ValueError("prospective_wwm_candidate_campaign_entry_invalid")
            parsed.append(entry)
        entries[system] = parsed
    return campaign_id, _parse_datetime(payload["evaluation_time_utc"]), entries


def main() -> None:
    args = parse_args()
    if args.report.exists():
        raise ValueError("prospective_wwm_candidate_score_overwrite_forbidden")
    report = compile_prospective_wwm_candidate_score(
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
