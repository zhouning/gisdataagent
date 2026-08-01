#!/usr/bin/env python3
"""Test phase-lead predictor selection across two exposed historical windows."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel_v2.physical_online_residual_adaptation import (
    PhysicalOnlineResidualAdaptationConfig,
)

if __package__:
    from scripts import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    from scripts import (
        evaluate_geospatial_kernel_physical_online_residual_adaptation as online,
    )
else:
    import evaluate_geospatial_kernel_action_innovation_cross_system as cross
    import evaluate_geospatial_kernel_physical_online_residual_adaptation as online


REPO_ROOT = Path(__file__).resolve().parents[1]
EVALUATOR_PATH = Path(__file__).resolve()
DEFAULT_COMPARISON_REPORT = online.DEFAULT_COMPARISON_REPORT
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/geospatial_kernel_phase_lead_mapping_transfer_posthoc_report.json"
)
SCHEMA = "gwm.geotransport.phase_lead_mapping_transfer_posthoc.v1"
CANDIDATE_PREDICTORS_BY_TARGET = {
    1: (3, 6, 12),
    3: (6, 12),
    6: (12,),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comparison-report",
        type=Path,
        default=DEFAULT_COMPARISON_REPORT,
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def compile_phase_lead_mapping_transfer_posthoc(
    *,
    comparison_report_path: Path = DEFAULT_COMPARISON_REPORT,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Select predictor leads on the earlier window and replay them later."""

    comparison_body, comparison = online._load_comparison_report(comparison_report_path)
    primary_descriptor = comparison["outputs"]["primary_predictions"]
    replication_descriptor = comparison["outputs"]["replication_predictions"]
    primary_body = cross._read_verified(primary_descriptor)
    replication_body = cross._read_verified(replication_descriptor)
    default_config = PhysicalOnlineResidualAdaptationConfig()
    default_mapping = dict(default_config.trajectory_predictor_horizon_pairs)

    candidate_results: dict[str, list[dict[str, Any]]] = {}
    selected_mapping: dict[int, int] = {}
    replication_best_mapping: dict[int, int] = {}
    selection_diagnostics: dict[str, dict[str, Any]] = {}
    causal_ordering_passed = True
    for target_horizon, predictor_horizons in CANDIDATE_PREDICTORS_BY_TARGET.items():
        records = []
        for predictor_horizon in predictor_horizons:
            mapping = tuple(
                (
                    horizon,
                    predictor_horizon if horizon == target_horizon else default_mapping[horizon],
                )
                for horizon in default_config.adaptive_forecast_horizons_hours
            )
            config = PhysicalOnlineResidualAdaptationConfig(
                trajectory_predictor_horizon_pairs=mapping
            )
            _, primary = online._compile_window(primary_body, config=config)
            _, replication = online._compile_window(
                replication_body,
                config=config,
            )
            causal_ordering_passed = causal_ordering_passed and all(
                window["execution"]["future_target_observation_used_before_availability"] is False
                for window in (primary, replication)
            )
            records.append(
                {
                    "predictor_horizon_hours": predictor_horizon,
                    "primary_window": _horizon_result(
                        primary,
                        target_horizon=target_horizon,
                    ),
                    "replication_window": _horizon_result(
                        replication,
                        target_horizon=target_horizon,
                    ),
                }
            )

        primary_ranking = sorted(
            records,
            key=lambda record: (
                record["primary_window"]["online_rmse_m3s"],
                record["predictor_horizon_hours"],
            ),
        )
        replication_ranking = sorted(
            records,
            key=lambda record: (
                record["replication_window"]["online_rmse_m3s"],
                record["predictor_horizon_hours"],
            ),
        )
        selected = int(primary_ranking[0]["predictor_horizon_hours"])
        replication_best = int(replication_ranking[0]["predictor_horizon_hours"])
        selected_mapping[target_horizon] = selected
        replication_best_mapping[target_horizon] = replication_best
        candidate_results[str(target_horizon)] = sorted(
            records,
            key=lambda record: record["predictor_horizon_hours"],
        )
        selection_diagnostics[str(target_horizon)] = {
            "candidate_count": len(records),
            "selection_is_nontrivial": len(records) > 1,
            "primary_selected_predictor_horizon_hours": selected,
            "replication_best_predictor_horizon_hours": replication_best,
            "primary_selection_matches_replication_best": (selected == replication_best),
            "full_predictor_ranking_replicated": [
                record["predictor_horizon_hours"] for record in primary_ranking
            ]
            == [record["predictor_horizon_hours"] for record in replication_ranking],
        }

    selected_config = PhysicalOnlineResidualAdaptationConfig(
        trajectory_predictor_horizon_pairs=tuple(
            (target, selected_mapping[target])
            for target in default_config.adaptive_forecast_horizons_hours
        )
    )
    selected_windows = [
        online._compile_window(body, config=selected_config)[1]
        for body in (primary_body, replication_body)
    ]
    nontrivial_targets = [
        str(target)
        for target, predictors in CANDIDATE_PREDICTORS_BY_TARGET.items()
        if len(predictors) > 1
    ]
    selected_mapping_matches_replication = all(
        selection_diagnostics[target]["primary_selection_matches_replication_best"]
        for target in nontrivial_targets
    )
    full_ranking_replicated = all(
        selection_diagnostics[target]["full_predictor_ranking_replicated"]
        for target in nontrivial_targets
    )
    selected_beats_raw = all(
        window["comparison"]["online_beats_raw_physical_all_horizons"]
        for window in selected_windows
    )

    return {
        "schema": SCHEMA,
        "status": "phase_lead_mapping_historical_transfer_diagnostic_complete",
        "generated_at": _aware_datetime(
            generated_at if generated_at is not None else datetime.now(UTC)
        ).isoformat(),
        "implementation_artifacts": {
            "diagnostic_evaluator": _artifact(
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
            "comparison_report": _artifact(
                comparison_report_path,
                comparison_body,
            ),
            "primary_target_comparison_rows": dict(primary_descriptor),
            "replication_target_comparison_rows": dict(replication_descriptor),
        },
        "diagnostic_contract": {
            "development_window": "primary_window_2022_03_31_to_2022_04_28",
            "transfer_window": "replication_window_2022_11_10_to_2022_12_08",
            "selection_metric": "minimum_full_window_online_rmse_m3s",
            "candidate_predictor_horizons_by_target_horizon": {
                str(target): list(predictors)
                for target, predictors in CANDIDATE_PREDICTORS_BY_TARGET.items()
            },
            "horizon_specialized_online_states_are_independent": True,
            "mapping_selected_only_from_primary_window_in_this_diagnostic": True,
            "replication_window_not_used_for_mapping_selection": True,
        },
        "candidate_results_by_target_horizon": candidate_results,
        "selection_diagnostics_by_target_horizon": selection_diagnostics,
        "selected_mapping_by_primary_window": {
            str(target): predictor for target, predictor in selected_mapping.items()
        },
        "replication_best_mapping": {
            str(target): predictor for target, predictor in replication_best_mapping.items()
        },
        "diagnostic_interpretation": {
            "causal_maturity_ordering_passed_for_all_candidate_replays": (causal_ordering_passed),
            "primary_selected_mapping_matches_v4_fixed_mapping": (
                selected_config.trajectory_predictor_horizon_pairs
                == default_config.trajectory_predictor_horizon_pairs
            ),
            "primary_selected_mapping_matches_replication_best_for_nontrivial_targets": (
                selected_mapping_matches_replication
            ),
            "full_predictor_ranking_replicated_for_nontrivial_targets": (full_ranking_replicated),
            "selected_mapping_beats_raw_physical_all_horizons_in_both_windows": (
                selected_beats_raw
            ),
            "phase_lead_hypothesis_survives_historical_temporal_transfer_diagnostic": (
                selected_mapping_matches_replication
                and full_ranking_replicated
                and selected_beats_raw
            ),
            "routing_celerity_error_identified": False,
        },
        "information_boundary": {
            "both_historical_target_windows_exposed_before_diagnostic_design": True,
            "replication_window_occurs_after_development_window": True,
            "replication_window_is_fresh_prospective_validation": False,
            "diagnostic_may_promote_candidate": False,
            "operational_issue_time_vintages_verified": False,
        },
        "claim_boundary": {
            "historical_mapping_transfer_diagnostic_executed": True,
            "phase_lead_mapping_admitted": False,
            "geospatial_kernel_validated": False,
            "operational_forecast_validated": False,
            "runtime_default_enabled": False,
        },
    }


def _horizon_result(
    window: Mapping[str, Any],
    *,
    target_horizon: int,
) -> dict[str, Any]:
    horizon = str(target_horizon)
    metrics = window["metrics_by_horizon"][horizon]
    diagnostic = window["paired_loss_diagnostic_by_horizon"][horizon]
    return {
        "online_rmse_m3s": metrics["physical_online_residual_adaptation"]["rmse_m3s"],
        "raw_physical_rmse_m3s": metrics["physical_open_loop"]["rmse_m3s"],
        "online_minus_raw_physical_rmse_m3s": window["comparison"]["per_horizon"][horizon][
            "online_minus_raw_physical_rmse_m3s"
        ],
        "paired_squared_error_improvement_z_score": diagnostic["improvement_z_score"],
        "paired_squared_error_improvement_hac_supported": diagnostic[
            "mean_improvement_exceeds_1_96_hac_standard_errors"
        ],
    }


def _artifact(path: Path, body: bytes) -> dict[str, object]:
    try:
        relative_path = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError:
        relative_path = str(path.resolve())
    return {
        "path": relative_path,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("phase_lead_mapping_generated_at_invalid")
    return value.astimezone(UTC)


def _json_body(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> None:
    args = parse_args()
    report = compile_phase_lead_mapping_transfer_posthoc(
        comparison_report_path=args.comparison_report,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_bytes(_json_body(report))
    print(f"status={report['status']}")
    print(f"selected_mapping={report['selected_mapping_by_primary_window']}")
    print(
        "historical_transfer_survived="
        f"{report['diagnostic_interpretation']['phase_lead_hypothesis_survives_historical_temporal_transfer_diagnostic']}"
    )


if __name__ == "__main__":
    main()
