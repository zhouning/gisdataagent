"""Urban Cup Track 2 Vibe Research submission readiness gates."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .data_foundation import audit_uwm_data_foundation_manifest
from .openaq_temporal_benchmark import validate_openaq_observed_temporal_benchmark
from .world_model_evidence_readiness import build_world_model_evidence_readiness


TRACK2_INITIAL_REVIEW_DEADLINE = "2026-07-22"
TRACK2_INITIAL_FEEDBACK_DATE = "2026-07-29"
TRACK2_FINAL_PRESENTATION_DATES = ["2026-08-08", "2026-08-09"]

TRACK2_REQUIRED_DELIVERABLES = {
    "research_report": {
        "label": "research report",
        "required": True,
        "must_cover": [
            "research_question",
            "data_sources",
            "methods",
            "main_findings",
            "urban_science_significance",
        ],
    },
    "data_description": {
        "label": "data description",
        "required": True,
        "must_cover": [
            "data_sources",
            "licenses_or_access_boundaries",
            "claim_boundaries",
            "synthetic_or_proxy_flags",
        ],
    },
    "reproducible_code": {
        "label": "reproducible code",
        "required": True,
        "must_cover": [
            "runtime_contracts",
            "tests",
            "manifest_audit",
            "evaluation_gates",
        ],
    },
    "ai_collaboration_log": {
        "label": "AI collaboration process record",
        "required": True,
        "must_cover": [
            "research_log",
            "tool_or_dialogue_record",
            "modeling_decisions",
            "failed_or_rejected_claims",
        ],
    },
}

AI_URBAN_SCIENTIST_STAGE_MAP = {
    "idea_generation": {
        "source_tool_stage": "Idea Generation",
        "uwm_usage": "livability research question and novelty framing",
    },
    "data_seeking": {
        "source_tool_stage": "Data Seeking",
        "uwm_usage": "data foundation manifest and MMFE ingestion",
    },
    "paper_planning": {
        "source_tool_stage": "Paper Planning",
        "uwm_usage": "world-model evaluation design and claim boundary planning",
    },
    "paper_writing": {
        "source_tool_stage": "Paper Writing",
        "uwm_usage": "initial report, data statement, reproducibility package, research log",
    },
}


def build_track2_readiness_matrix(
    artifacts: dict[str, dict[str, Any]],
    *,
    current_date: str,
    data_foundation_audit: dict[str, Any] | None = None,
    observed_temporal_benchmark: dict[str, Any] | None = None,
    data_foundation_evidence_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a readiness matrix for Urban Cup Track 2 initial review."""

    deliverables: dict[str, dict[str, Any]] = {}
    missing_required: list[str] = []
    partial_required: list[str] = []
    for artifact_id, requirement in TRACK2_REQUIRED_DELIVERABLES.items():
        artifact = artifacts.get(artifact_id, {})
        status = str(artifact.get("status") or "missing")
        deliverables[artifact_id] = {
            "label": requirement["label"],
            "required": requirement["required"],
            "status": status,
            "path": artifact.get("path"),
            "must_cover": requirement["must_cover"],
            "notes": artifact.get("notes", ""),
        }
        if requirement["required"] and status == "missing":
            missing_required.append(artifact_id)
        if requirement["required"] and status == "partial":
            partial_required.append(artifact_id)

    ready = not missing_required and not partial_required
    matrix = {
        "schema": "uwm.track2_submission_readiness.v1",
        "competition": "Urban Cup 2026 Track 2 Vibe Research",
        "initial_review_deadline": TRACK2_INITIAL_REVIEW_DEADLINE,
        "days_to_initial_review_deadline": _days_between(current_date, TRACK2_INITIAL_REVIEW_DEADLINE),
        "initial_feedback_date": TRACK2_INITIAL_FEEDBACK_DATE,
        "final_presentation_dates": TRACK2_FINAL_PRESENTATION_DATES,
        "ready_for_initial_submission": ready,
        "missing_required_artifacts": missing_required,
        "partial_required_artifacts": partial_required,
        "deliverables": deliverables,
        "ai_urban_scientist_alignment": AI_URBAN_SCIENTIST_STAGE_MAP,
        "next_actions": _next_actions(missing_required, partial_required),
    }
    if data_foundation_audit is not None:
        matrix["data_foundation_readiness"] = _data_foundation_readiness(data_foundation_audit)
        for action in data_foundation_audit.get("public_acquisition_queue", []):
            if action not in matrix["next_actions"]:
                matrix["next_actions"].append(action)
    if observed_temporal_benchmark is not None:
        observed_readiness = _observed_temporal_validation_readiness(observed_temporal_benchmark)
        matrix["observed_validation_readiness"] = observed_readiness
        for action in observed_readiness["next_actions"]:
            if action not in matrix["next_actions"]:
                matrix["next_actions"].append(action)
    if data_foundation_evidence_gate is not None:
        world_model_readiness = build_world_model_evidence_readiness(
            data_foundation_evidence_gate
        )
        matrix["world_model_evidence_readiness"] = world_model_readiness
        for action in world_model_readiness["next_actions"]:
            if action not in matrix["next_actions"]:
                matrix["next_actions"].append(action)
    return matrix


def build_uwm_default_artifact_inventory(repo_root: str | Path) -> dict[str, dict[str, Any]]:
    """Inspect the current repo for UWM Track 2 submission artifacts."""

    root = Path(repo_root)
    return {
        "research_report": _artifact_status(
            root / "docs/reports/uwm_track2_initial_report.md",
            fallback_path="docs/reports/uwm_track2_initial_report.md",
            partial_path=root / "docs/reports/uwm_track2_research_log.md",
            partial_note="research log exists, but a complete initial research report is still required",
        ),
        "data_description": _artifact_status(
            root / "docs/reports/uwm_data_foundation_manifest.md",
            fallback_path="docs/reports/uwm_data_foundation_manifest.md",
        ),
        "reproducible_code": _artifact_status(
            root / "data_agent/uwm",
            fallback_path="data_agent/uwm",
        ),
        "ai_collaboration_log": _artifact_status(
            root / "docs/reports/uwm_track2_research_log.md",
            fallback_path="docs/reports/uwm_track2_research_log.md",
        ),
    }


def build_uwm_default_track2_readiness_matrix(
    repo_root: str | Path,
    *,
    current_date: str,
) -> dict[str, Any]:
    """Build Track 2 readiness from the repository's prepared UWM artifacts."""

    root = Path(repo_root)
    manifest_path = root / "docs/reports/uwm_data_foundation_manifest.csv"
    observed_temporal_benchmark_path = (
        root
        / "data/uwm_public_proxy/chongqing_central/openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json"
    )
    evidence_gate_path = (
        root
        / "data/uwm_public_proxy/chongqing_central/data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json"
    )
    return build_track2_readiness_matrix(
        build_uwm_default_artifact_inventory(root),
        current_date=current_date,
        data_foundation_audit=(
            audit_uwm_data_foundation_manifest(manifest_path)
            if manifest_path.exists()
            else None
        ),
        observed_temporal_benchmark=_read_json_if_exists(observed_temporal_benchmark_path),
        data_foundation_evidence_gate=_read_json_if_exists(evidence_gate_path),
    )


def _artifact_status(
    path: Path,
    *,
    fallback_path: str,
    partial_path: Path | None = None,
    partial_note: str = "",
) -> dict[str, Any]:
    if path.exists():
        return {"status": "available", "path": fallback_path}
    if partial_path is not None and partial_path.exists():
        return {"status": "partial", "path": fallback_path, "notes": partial_note}
    return {"status": "missing", "path": fallback_path}


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else None


def _days_between(current_date: str, deadline: str) -> int:
    return (date.fromisoformat(deadline) - date.fromisoformat(current_date)).days


def _next_actions(missing_required: list[str], partial_required: list[str]) -> list[str]:
    actions = []
    if "research_report" in missing_required or "research_report" in partial_required:
        actions.append("draft_initial_research_report")
    if "data_description" in missing_required or "data_description" in partial_required:
        actions.append("complete_data_statement_and_reproducibility_notes")
    if "reproducible_code" in missing_required or "reproducible_code" in partial_required:
        actions.append("package_reproducible_code_and_test_commands")
    if "ai_collaboration_log" in missing_required or "ai_collaboration_log" in partial_required:
        actions.append("complete_ai_collaboration_research_log")
    actions.append("advance_data_driven_holdout_validation")
    return actions


def _data_foundation_readiness(data_foundation_audit: dict[str, Any]) -> dict[str, Any]:
    missing_roles = list(data_foundation_audit.get("missing_required_roles") or [])
    empirical_blockers = list(data_foundation_audit.get("empirical_superiority_blockers") or [])
    return {
        "claim_ceiling": data_foundation_audit.get("claim_ceiling", "not_for_claim"),
        "required_roles_complete": not missing_roles,
        "empirical_superiority_ready": not missing_roles and not empirical_blockers,
        "missing_required_roles": missing_roles,
        "empirical_superiority_blockers": empirical_blockers,
        "public_acquisition_queue": list(data_foundation_audit.get("public_acquisition_queue") or []),
    }


def _observed_temporal_validation_readiness(benchmark: dict[str, Any]) -> dict[str, Any]:
    validation = validate_openaq_observed_temporal_benchmark(benchmark)
    claim_boundary = benchmark.get("claim_boundary") if isinstance(benchmark.get("claim_boundary"), dict) else {}
    temporal_ready = (
        validation["valid"]
        and bool(benchmark.get("observed_temporal_state_advantage_over_static_baseline"))
        and claim_boundary.get("max_claim_level") == "bounded_support"
        and benchmark.get("empirical_superiority_claim") is False
    )
    suite_ready = temporal_ready and bool(
        benchmark.get("observed_temporal_state_advantage_over_static_baseline_suite")
    )
    traditional_baseline_suite = list(benchmark.get("traditional_baseline_suite") or [])
    overall_sign_tests = (
        benchmark.get("overall_sign_tests")
        if isinstance(benchmark.get("overall_sign_tests"), dict)
        else {}
    )
    temporal_order_negative_control = (
        benchmark.get("temporal_order_negative_control_summary")
        if isinstance(benchmark.get("temporal_order_negative_control_summary"), dict)
        else {}
    )
    pm25 = _pollutant_result(benchmark, "pm25")
    pm25_best_static = (
        pm25.get("best_traditional_static_baseline")
        if isinstance(pm25.get("best_traditional_static_baseline"), dict)
        else {}
    )
    pm25_best_static_method = str(pm25_best_static.get("method") or "")
    pm25_baseline_suite = (
        pm25.get("traditional_static_baseline_suite")
        if isinstance(pm25.get("traditional_static_baseline_suite"), dict)
        else {}
    )
    pm25_best_static_sign_test = (
        pm25_baseline_suite.get(pm25_best_static_method, {}).get("dynamic_sign_test", {})
        if pm25_best_static_method
        else {}
    )
    pm25_temporal_order_control = (
        pm25.get("temporal_order_negative_control")
        if isinstance(pm25.get("temporal_order_negative_control"), dict)
        else {}
    )
    return {
        "schema": "uwm.observed_validation_readiness.v1",
        "benchmark_id": benchmark.get("benchmark_id"),
        "temporal_state_prediction_ready": temporal_ready,
        "temporal_state_prediction_suite_ready": suite_ready,
        "temporal_state_prediction_suite_significant_at_0_05": (
            suite_ready and _suite_significant_at_0_05(traditional_baseline_suite, overall_sign_tests)
        ),
        "temporal_order_negative_control_passed": bool(
            temporal_order_negative_control.get("all_pollutants_ordered_temporal_state_advantage")
        ),
        "supported_claim": (
            benchmark.get("supported_claim")
            if temporal_ready
            else "no_observed_temporal_state_prediction_claim"
        ),
        "claim_boundary": {
            "max_claim_level": claim_boundary.get("max_claim_level") if temporal_ready else "not_for_claim",
            "reason": claim_boundary.get("reason", ""),
        },
        "pollutant_count": _safe_int(benchmark.get("pollutant_count")),
        "observation_count": _safe_int(benchmark.get("observation_count")),
        "holdout_count": _safe_int(benchmark.get("holdout_count")),
        "traditional_baseline_suite": traditional_baseline_suite,
        "overall_sign_tests": overall_sign_tests,
        "temporal_order_negative_control_summary": temporal_order_negative_control,
        "overall_holdout_win_count": _safe_int(benchmark.get("overall_holdout_win_count")),
        "overall_holdout_win_rate": _safe_float(benchmark.get("overall_holdout_win_rate")),
        "pm25_holdout_win_count": _safe_int(pm25.get("holdout_win_count")),
        "pm25_holdout_count": _safe_int(pm25.get("holdout_count")),
        "pm25_holdout_win_rate": _safe_float(pm25.get("holdout_win_rate")),
        "pm25_static_mean_baseline_mae": _safe_float(pm25.get("static_mean_baseline_mae")),
        "pm25_uwm_dynamic_persistence_mae": _safe_float(pm25.get("uwm_dynamic_persistence_mae")),
        "pm25_best_static_baseline_method": pm25_best_static_method,
        "pm25_best_static_baseline_mae": _safe_float(pm25_best_static.get("mae")),
        "pm25_sign_test_vs_best_static_p_value": _safe_float(
            pm25_best_static_sign_test.get("one_sided_p_value")
        ),
        "pm25_ordered_mae_advantage_over_shuffled": _safe_float(
            pm25_temporal_order_control.get("ordered_mae_advantage")
        ),
        "pm25_beats_all_traditional_static_baselines": bool(
            pm25.get("beats_all_traditional_static_baselines")
        ),
        "policy_outcome_superiority_ready": False,
        "empirical_superiority_claim": False,
        "validation_errors": validation["errors"],
        "limitations": list(benchmark.get("limitations") or []),
        "remaining_gates": [
            "observed_policy_outcome_holdout_required",
            "planner_regret_observed_outcome_required",
            "causal_policy_effect_validation_required",
        ],
        "next_actions": [
            "advance_observed_policy_outcome_holdout_validation",
            "expand_scene_aligned_station_holdout_validation",
        ],
    }


def _pollutant_result(benchmark: dict[str, Any], pollutant: str) -> dict[str, Any]:
    for result in benchmark.get("per_pollutant_results") or []:
        if str(result.get("pollutant") or "").lower() == pollutant:
            return result
    return {}


def _suite_significant_at_0_05(
    traditional_baseline_suite: list[str],
    overall_sign_tests: dict[str, Any],
) -> bool:
    if not traditional_baseline_suite:
        return False
    for method in traditional_baseline_suite:
        sign_test = overall_sign_tests.get(method)
        if not isinstance(sign_test, dict) or "one_sided_p_value" not in sign_test:
            return False
        if _safe_float(sign_test.get("one_sided_p_value")) > 0.05:
            return False
    return True


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
