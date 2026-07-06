"""Evidence gate over prepared UWM data-foundation artifacts."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


UWM_DATA_FOUNDATION_EVIDENCE_GATE_SCHEMA = "uwm.data_foundation_evidence_gate.v1"

ACCEPTED_SYNTHETIC_STATUSES = [
    "real",
    "public_proxy",
    "fitted_proxy",
    "semi_synthetic",
    "synthetic",
    "restricted_expected",
]


def build_uwm_data_foundation_evidence_gate(
    *,
    manifest_path: str | Path,
    openaq_temporal_benchmark_path: str | Path,
    tap_external_dynamics_path: str | Path,
    learned_rollout_path: str | Path,
    livability_intervention_package_path: str | Path,
    local_planning_inventory_path: str | Path,
    admin_spatial_graph_path: str | Path,
    gate_id: str,
    created_at: str,
) -> dict[str, Any]:
    """Summarize claim-safe evidence from actual prepared UWM artifacts."""

    manifest_rows = _read_manifest_rows(manifest_path)
    openaq_benchmark = _read_json(openaq_temporal_benchmark_path)
    tap_external_dynamics = _read_json(tap_external_dynamics_path)
    learned_rollout = _read_json(learned_rollout_path)
    intervention_package = _read_json(livability_intervention_package_path)
    local_inventory_rows = _read_csv_rows(local_planning_inventory_path)
    admin_graph = _read_json(admin_spatial_graph_path)

    openaq_slice = _openaq_temporal_state_slice(
        openaq_benchmark,
        source_artifact_exists=Path(openaq_temporal_benchmark_path).exists(),
    )
    tap_transition_slice = _tap_external_temporal_transition_slice(
        tap_external_dynamics,
        source_artifact_exists=Path(tap_external_dynamics_path).exists(),
    )
    rollout_slice = _learned_rollout_slice(
        learned_rollout,
        source_artifact_exists=Path(learned_rollout_path).exists(),
    )
    intervention_slice = _livability_intervention_slice(
        intervention_package,
        source_artifact_exists=Path(livability_intervention_package_path).exists(),
        tap_external_temporal_transition_ready=_external_temporal_transition_superiority(
            tap_transition_slice
        ),
    )
    claim_guard = _claim_guard(manifest_rows)
    return {
        "schema": UWM_DATA_FOUNDATION_EVIDENCE_GATE_SCHEMA,
        "gate_id": gate_id,
        "created_at": created_at,
        "data_foundation_scope": _data_foundation_scope(manifest_rows),
        "evidence_slices": {
            "openaq_observed_temporal_state": openaq_slice,
            "tap_external_temporal_transition": tap_transition_slice,
            "learned_world_model_rollout": rollout_slice,
            "livability_intervention_package": intervention_slice,
            "local_planning_data_foundation": _local_planning_data_foundation_slice(
                local_inventory_rows,
                source_artifact_exists=Path(local_planning_inventory_path).exists(),
            ),
            "admin_spatial_adjacency_graph": _admin_spatial_graph_slice(
                admin_graph,
                source_artifact_exists=Path(admin_spatial_graph_path).exists(),
            ),
        },
        "observed_state_prediction_superiority_claim": _observed_state_prediction_superiority(
            openaq_slice
        ),
        "external_temporal_transition_superiority_claim": _external_temporal_transition_superiority(
            tap_transition_slice
        ),
        "observed_policy_outcome_superiority_claim": False,
        "empirical_superiority_claim": False,
        "supported_claims": _supported_claims(
            openaq_slice,
            tap_transition_slice,
            rollout_slice,
            intervention_slice,
        ),
        "claim_guard": claim_guard,
        "remaining_gates": _remaining_gates(
            claim_guard,
            tap_external_temporal_transition_ready=_external_temporal_transition_superiority(
                tap_transition_slice
            ),
        ),
    }


def _data_foundation_scope(rows: list[dict[str, str]]) -> dict[str, Any]:
    status_counts = Counter(row.get("synthetic_status", "") for row in rows)
    source_counts = Counter(row.get("source_type", "") for row in rows)
    access_counts = Counter(row.get("access_status", "") for row in rows)
    return {
        "manifest_row_count": len(rows),
        "accepted_synthetic_statuses": ACCEPTED_SYNTHETIC_STATUSES,
        "synthetic_status_counts": {
            status: status_counts.get(status, 0)
            for status in ACCEPTED_SYNTHETIC_STATUSES
        },
        "source_type_counts": dict(sorted(source_counts.items())),
        "access_status_counts": dict(sorted(access_counts.items())),
        "scope_note": (
            "all prepared UWM data-foundation assets may be used, but claims are gated by "
            "synthetic_status, source_type, access_status and artifact-level evidence"
        ),
    }


def _openaq_temporal_state_slice(
    benchmark: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    pm25 = _pollutant_result(benchmark, "pm25")
    best_pm25 = pm25.get("best_traditional_static_baseline") or {}
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": benchmark.get("schema"),
        "scope": "observed_temporal_state_prediction_not_policy_outcome",
        "source_dataset_ids": benchmark.get("source_dataset_ids") or [],
        "pollutant_count": _int(benchmark.get("pollutant_count")),
        "observation_count": _int(benchmark.get("observation_count")),
        "holdout_count": _int(benchmark.get("holdout_count")),
        "overall_holdout_win_count": _int(benchmark.get("overall_holdout_win_count")),
        "overall_holdout_win_rate": _float(benchmark.get("overall_holdout_win_rate")),
        "overall_sign_tests": benchmark.get("overall_sign_tests") or {},
        "temporal_order_negative_control_passed": bool(
            (
                benchmark.get("temporal_order_negative_control_summary")
                or {}
            ).get("all_pollutants_ordered_temporal_state_advantage")
        ),
        "pm25_dynamic_mae": _float(pm25.get("uwm_dynamic_persistence_mae")),
        "pm25_best_static_mae": _float(best_pm25.get("mae")),
        "supported_claim": benchmark.get("supported_claim"),
        "claim_level": (benchmark.get("claim_boundary") or {}).get("max_claim_level"),
        "limitations": benchmark.get("limitations") or [],
        "empirical_superiority_claim": bool(benchmark.get("empirical_superiority_claim")),
    }


def _tap_external_temporal_transition_slice(
    report: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    training = report.get("training_summary") or {}
    overall = report.get("overall_results") or {}
    negative_controls = report.get("negative_control_results") or {}
    temporal_control = negative_controls.get("temporal_order_rotation_control") or {}
    leakage_guard = negative_controls.get("future_label_leakage_guard") or {}
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": report.get("schema"),
        "scope": "tap_external_temporal_transition_without_spatial_claim",
        "source_dataset_ids": report.get("source_dataset_ids") or [],
        "series_count": _int(training.get("series_count")),
        "holdout_count": _int(training.get("holdout_count")),
        "best_spatial_method": overall.get("best_spatial_method"),
        "best_transition_mae": _float(overall.get("best_spatial_mae")),
        "best_traditional_static_mae": _float(overall.get("best_traditional_static_mae")),
        "best_non_spatial_dynamic_mae": _float(
            overall.get("best_non_spatial_dynamic_mae")
        ),
        "mae_reduction_vs_best_static": _float(
            overall.get("spatial_mae_reduction_vs_best_static")
        ),
        "mae_reduction_vs_best_non_spatial_dynamic": _float(
            overall.get("spatial_mae_reduction_vs_best_non_spatial_dynamic")
        ),
        "paired_win_rate_vs_best_non_spatial_dynamic": _float(
            overall.get("paired_win_rate_vs_best_non_spatial_dynamic")
        ),
        "spatial_negative_control_passed": bool(
            overall.get("spatial_negative_control_passed")
        ),
        "temporal_order_negative_control_passed": _float(
            temporal_control.get("ordered_advantage")
        )
        > 0.0,
        "future_label_leakage_guard_passed": bool(leakage_guard.get("passed")),
        "supported_claim": report.get("supported_claim"),
        "claim_level": (report.get("claim_boundary") or {}).get("max_claim_level"),
        "spatial_attribution_claim": False,
        "policy_outcome_claim": False,
        "empirical_superiority_claim": bool(report.get("empirical_superiority_claim")),
        "limitations": report.get("limitations") or [],
    }


def _learned_rollout_slice(
    report: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    planner = report.get("learned_rollout_planner") or {}
    training = report.get("training_summary") or {}
    holdout = report.get("holdout_metrics") or {}
    baseline = report.get("baseline_metrics") or {}
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": report.get("schema"),
        "scope": "simulator_replay_learned_dynamics_not_observed_policy_outcome",
        "transition_count": _int(training.get("transition_count")),
        "holdout_count": _int(training.get("holdout_count")),
        "holdout_reward_mae": _float(holdout.get("reward_mae")),
        "train_mean_reward_mae": _float(baseline.get("train_mean_reward_mae")),
        "reward_win_count_vs_train_mean": _int(holdout.get("reward_win_count_vs_train_mean")),
        "imagined_advantage_over_static": _float(
            planner.get("imagined_advantage_over_static_single_step")
        ),
        "imagined_advantage_over_one_step": _float(
            planner.get("imagined_advantage_over_one_step_policy")
        ),
        "selected_sequence": (planner.get("selected_sequence") or {}).get("action_sequence") or [],
        "supported_claim": report.get("supported_claim"),
        "claim_level": (report.get("claim_boundary") or {}).get("max_claim_level"),
        "empirical_superiority_claim": bool(report.get("empirical_superiority_claim")),
    }


def _livability_intervention_slice(
    package: dict[str, Any],
    *,
    source_artifact_exists: bool,
    tap_external_temporal_transition_ready: bool = False,
) -> dict[str, Any]:
    reported_gates = package.get("remaining_gates") or []
    remaining_gates = list(reported_gates)
    if tap_external_temporal_transition_ready:
        remaining_gates = [
            gate
            for gate in remaining_gates
            if gate != "tap_or_authoritative_air_quality_required"
        ]
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": package.get("schema"),
        "scope": "business_theory_aligned_proxy_package_not_observed_policy_outcome",
        "synthetic_status": package.get("synthetic_status"),
        "supported_claim": package.get("supported_claim"),
        "claim_level": (package.get("claim_boundary") or {}).get("max_claim_level"),
        "action_count": (package.get("multi_step_plan") or {}).get("action_count"),
        "predicted_delta": (package.get("before_after_indicators") or {}).get(
            "predicted_delta"
        )
        or {},
        "equity_status": (package.get("equity_conclusion") or {}).get("status"),
        "reported_remaining_gates": reported_gates,
        "remaining_gates": remaining_gates,
        "empirical_superiority_claim": bool(package.get("empirical_superiority_claim")),
    }


def _local_planning_data_foundation_slice(
    rows: list[dict[str, str]],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    wanted_ids = {
        "gaode_poi_2024",
        "chongqing_central_buildings_2021",
        "chongqing_osm_roads_2021",
        "chongqing_unicom_commuting_2023_local",
    }
    asset_counts = {}
    for row in rows:
        asset_id = str(row.get("asset_id") or "")
        if asset_id not in wanted_ids:
            continue
        asset_counts[asset_id] = {
            "asset_kind": row.get("asset_kind"),
            "status": row.get("status"),
            "feature_count": _int(row.get("feature_count")),
            "row_count": _int(row.get("row_count")),
            "geometry_type": row.get("geometry_type"),
            "crs": row.get("crs"),
            "uwm_roles": row.get("uwm_roles"),
        }
    return {
        "source_artifact_exists": source_artifact_exists,
        "scope": "prepared_local_planning_data_foundation",
        "asset_counts": asset_counts,
        "claim_level": "fragile",
        "empirical_superiority_claim": False,
        "limitations": [
            "restricted_local_sample_terms_pending",
            "not_policy_intervention_outcome",
        ],
    }


def _admin_spatial_graph_slice(
    graph: dict[str, Any],
    *,
    source_artifact_exists: bool,
) -> dict[str, Any]:
    summary = graph.get("summary") or {}
    return {
        "source_artifact_exists": source_artifact_exists,
        "schema": graph.get("schema"),
        "scope": "prepared_admin_boundary_adjacency_graph_not_mobility_graph",
        "node_count": _int(summary.get("node_count")),
        "edge_count": _int(summary.get("edge_count")),
        "isolated_node_count": _int(summary.get("isolated_node_count")),
        "edge_rule": summary.get("edge_rule"),
        "claim_level": (graph.get("claim_boundary") or {}).get("max_claim_level"),
        "empirical_superiority_claim": False,
    }


def _supported_claims(
    openaq_slice: dict[str, Any],
    tap_transition_slice: dict[str, Any],
    rollout_slice: dict[str, Any],
    intervention_slice: dict[str, Any],
) -> list[dict[str, Any]]:
    claims = []
    if _observed_state_prediction_superiority(openaq_slice):
        claims.append(
            {
                "claim": openaq_slice["supported_claim"],
                "scope": openaq_slice["scope"],
                "claim_level": openaq_slice["claim_level"],
                "policy_outcome_claim": False,
            }
        )
    if _external_temporal_transition_superiority(tap_transition_slice):
        claims.append(
            {
                "claim": tap_transition_slice["supported_claim"],
                "scope": tap_transition_slice["scope"],
                "claim_level": tap_transition_slice["claim_level"],
                "policy_outcome_claim": False,
                "spatial_attribution_claim": False,
            }
        )
    if rollout_slice.get("imagined_advantage_over_static", 0.0) > 0:
        claims.append(
            {
                "claim": rollout_slice["supported_claim"],
                "scope": rollout_slice["scope"],
                "claim_level": rollout_slice["claim_level"],
                "policy_outcome_claim": False,
            }
        )
    if intervention_slice.get("supported_claim"):
        claims.append(
            {
                "claim": intervention_slice["supported_claim"],
                "scope": intervention_slice["scope"],
                "claim_level": intervention_slice["claim_level"],
                "policy_outcome_claim": False,
            }
        )
    return claims


def _external_temporal_transition_superiority(tap_transition_slice: dict[str, Any]) -> bool:
    return (
        tap_transition_slice.get("source_artifact_exists") is True
        and tap_transition_slice.get("claim_level") == "bounded_support"
        and tap_transition_slice.get("supported_claim")
        == "tap_external_temporal_dynamics_advantage_without_spatial_claim"
        and _int(tap_transition_slice.get("series_count")) >= 1000
        and _int(tap_transition_slice.get("holdout_count")) >= 1000
        and _float(tap_transition_slice.get("best_transition_mae"))
        < _float(tap_transition_slice.get("best_traditional_static_mae"))
        and _float(tap_transition_slice.get("best_transition_mae"))
        < _float(tap_transition_slice.get("best_non_spatial_dynamic_mae"))
        and _float(tap_transition_slice.get("paired_win_rate_vs_best_non_spatial_dynamic"))
        > 0.5
        and tap_transition_slice.get("temporal_order_negative_control_passed") is True
        and tap_transition_slice.get("future_label_leakage_guard_passed") is True
        and tap_transition_slice.get("spatial_negative_control_passed") is False
    )


def _observed_state_prediction_superiority(openaq_slice: dict[str, Any]) -> bool:
    sign_tests = openaq_slice.get("overall_sign_tests") or {}
    static_mean_p = _float(
        (sign_tests.get("static_train_mean") or {}).get("one_sided_p_value"),
        default=1.0,
    )
    last_obs_p = _float(
        (sign_tests.get("static_last_train_observation") or {}).get("one_sided_p_value"),
        default=1.0,
    )
    return (
        openaq_slice.get("source_artifact_exists") is True
        and openaq_slice.get("claim_level") == "bounded_support"
        and _int(openaq_slice.get("observation_count")) >= 100
        and _int(openaq_slice.get("holdout_count")) >= 30
        and _float(openaq_slice.get("overall_holdout_win_rate")) > 0.5
        and static_mean_p < 0.05
        and last_obs_p < 0.05
        and openaq_slice.get("temporal_order_negative_control_passed") is True
    )


def _claim_guard(rows: list[dict[str, str]]) -> dict[str, Any]:
    blocked_statuses = {"synthetic", "semi_synthetic", "fitted_proxy", "smoke_only"}
    blocked_dataset_ids = [
        row.get("dataset_id", "")
        for row in rows
        if row.get("synthetic_status") in blocked_statuses
        or row.get("quality_status") == "smoke_only"
    ]
    return {
        "synthetic_or_smoke_blocked_from_empirical_policy_claim": True,
        "blocked_dataset_ids": sorted(dataset_id for dataset_id in blocked_dataset_ids if dataset_id),
        "rule": (
            "synthetic, semi_synthetic, fitted_proxy and smoke-only assets may support "
            "development or exploratory scaffolds, but cannot support observed policy "
            "outcome superiority claims"
        ),
    }


def _remaining_gates(
    claim_guard: dict[str, Any],
    *,
    tap_external_temporal_transition_ready: bool = False,
) -> list[str]:
    gates = [
        "observed_policy_outcome_required",
        "scene_aligned_station_calibrated_air_quality_holdout_required",
        "causal_policy_effect_validation_required",
        "external_observed_holdout_required",
    ]
    if not tap_external_temporal_transition_ready:
        gates.insert(1, "tap_or_authoritative_air_quality_required")
    if claim_guard.get("blocked_dataset_ids"):
        gates.append("synthetic_proxy_boundary_must_remain_visible")
    return gates


def _pollutant_result(benchmark: dict[str, Any], pollutant: str) -> dict[str, Any]:
    for result in benchmark.get("per_pollutant_results") or []:
        if result.get("pollutant") == pollutant:
            return result
    return {}


def _read_manifest_rows(path: str | Path) -> list[dict[str, str]]:
    return _read_csv_rows(path)


def _read_csv_rows(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _int(value: Any, default: int = 0) -> int:
    if value in {None, ""}:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    if value in {None, ""}:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
