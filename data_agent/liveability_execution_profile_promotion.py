"""Evidence-bound execution-profile selection for Liveability source 12.

The semantic IR profile is never selected merely because a caller omitted a
profile. The current semantic artifact must match an approved, checksum-
verified promotion record; otherwise the safe baseline is used.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from .abu_dhabi_artifact_registry import ROOT, current_artifact_manifest


ARTIFACT_ROOT = ROOT / "docs/customer/abu_dhabi_liveability_site_validation"
PROMOTION_PATH = ARTIFACT_ROOT / "liveability_v56_semantic_ir_default_promotion_20260915.json"
PROMOTION_SCHEMA = "gda.liveability-execution-profile-promotion.v1"
BASELINE_EXECUTION_PROFILE: Literal["baseline_sql"] = "baseline_sql"
SEMANTIC_IR_EXECUTION_PROFILE: Literal["semantic_ir_experimental"] = (
    "semantic_ir_experimental"
)
ExecutionProfile = Literal["baseline_sql", "semantic_ir_experimental"]


class LiveabilityExecutionProfilePromotionError(ValueError):
    """The local promotion record cannot authorize the semantic IR default."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LiveabilityExecutionProfilePromotionError(
            f"liveability_execution_profile_promotion_unreadable:{path.name}"
        ) from exc
    if not isinstance(payload, dict):
        raise LiveabilityExecutionProfilePromotionError(
            f"liveability_execution_profile_promotion_object_required:{path.name}"
        )
    return payload


def _load_evidence(descriptor: dict[str, Any], *, schema: str) -> dict[str, Any]:
    relative = Path(str(descriptor.get("path") or ""))
    expected_sha256 = str(descriptor.get("sha256") or "")
    if relative.is_absolute() or ".." in relative.parts or len(expected_sha256) != 64:
        raise LiveabilityExecutionProfilePromotionError(
            "liveability_execution_profile_promotion_evidence_descriptor_invalid"
        )
    path = (ROOT / relative).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise LiveabilityExecutionProfilePromotionError(
            "liveability_execution_profile_promotion_evidence_outside_repository"
        ) from exc
    if _sha256(path) != expected_sha256:
        raise LiveabilityExecutionProfilePromotionError(
            f"liveability_execution_profile_promotion_evidence_checksum_invalid:{path.name}"
        )
    payload = _load_json(path)
    if payload.get("schema") != schema:
        raise LiveabilityExecutionProfilePromotionError(
            f"liveability_execution_profile_promotion_evidence_schema_invalid:{path.name}"
        )
    return payload


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise LiveabilityExecutionProfilePromotionError(code)


def load_liveability_execution_profile_promotion() -> dict[str, Any]:
    """Return an approved decision only after all bindings still match."""

    promotion = _load_json(PROMOTION_PATH)
    _require(
        promotion.get("schema") == PROMOTION_SCHEMA,
        "liveability_execution_profile_promotion_schema_invalid",
    )
    _require(
        promotion.get("status") == "approved",
        "liveability_execution_profile_promotion_not_approved",
    )
    authorization = promotion.get("authorization") or {}
    _require(
        authorization.get("source_id") == 12,
        "liveability_execution_profile_promotion_source_invalid",
    )
    _require(
        authorization.get("default_execution_profile") == SEMANTIC_IR_EXECUTION_PROFILE,
        "liveability_execution_profile_promotion_default_invalid",
    )
    _require(
        authorization.get("rollback_execution_profile") == BASELINE_EXECUTION_PROFILE,
        "liveability_execution_profile_promotion_rollback_invalid",
    )

    evidence = promotion.get("evidence") or {}
    candidate = _load_evidence(
        evidence.get("candidate_stability") or {},
        schema="gda.product-nl2sql-stability-report.v1",
    )
    baseline = _load_evidence(
        evidence.get("baseline_stability") or {},
        schema="gda.product-nl2sql-stability-report.v1",
    )
    pairwise = _load_evidence(
        evidence.get("pairwise_stability") or {},
        schema="gda.nl2semantic2sql-pairwise-stability-comparison.v1",
    )
    bundle = current_artifact_manifest("liveability")
    source = bundle.get("source") or {}
    semantic = (bundle.get("artifacts") or {}).get("semantic") or {}
    promoted_semantic = promotion.get("semantic_artifact") or {}
    _require(
        source.get("source_id") == 12
        and source.get("discovery_fingerprint")
        == authorization.get("source_discovery_fingerprint"),
        "liveability_execution_profile_promotion_source_drift",
    )
    _require(
        semantic.get("path") == promoted_semantic.get("path")
        and semantic.get("sha256") == promoted_semantic.get("sha256")
        and bundle.get("semantic_version") == promoted_semantic.get("semantic_version"),
        "liveability_execution_profile_promotion_semantic_drift",
    )

    candidate_benchmark = candidate.get("benchmark") or {}
    baseline_benchmark = baseline.get("benchmark") or {}
    candidate_metrics = candidate.get("metrics") or {}
    baseline_metrics = baseline.get("metrics") or {}
    pairwise_metrics = (pairwise.get("metrics") or {}).get("all_matched_observations") or {}
    outcomes = pairwise_metrics.get("outcome_counts") or {}
    _require(
        candidate.get("status") == "candidate_stability_ready"
        and baseline.get("status") == "not_release_ready"
        and candidate_benchmark.get("execution_profile") == SEMANTIC_IR_EXECUTION_PROFILE
        and baseline_benchmark.get("execution_profile") == BASELINE_EXECUTION_PROFILE,
        "liveability_execution_profile_promotion_route_evidence_invalid",
    )
    for key in (
        "source_id",
        "discovery_fingerprint",
        "semantic_layer_version",
        "metric_contract_version",
        "model_requested",
        "reasoning_effort",
    ):
        _require(
            candidate_benchmark.get(key) == baseline_benchmark.get(key),
            f"liveability_execution_profile_promotion_pair_mismatch:{key}",
        )
    _require(
        candidate_benchmark.get("source_id") == 12
        and candidate_benchmark.get("discovery_fingerprint")
        == source.get("discovery_fingerprint")
        and candidate_benchmark.get("semantic_layer_version")
        == bundle.get("semantic_version")
        and candidate_benchmark.get("model_requested")
        == authorization.get("model_requested")
        and candidate_benchmark.get("reasoning_effort")
        == authorization.get("reasoning_effort"),
        "liveability_execution_profile_promotion_binding_invalid",
    )
    _require(
        candidate_metrics.get("case_count") == 76
        and candidate_metrics.get("case_run_count") == 380
        and candidate_metrics.get("case_run_pass_rate") == 1.0
        and candidate_metrics.get("safety_pass_rate") == 1.0
        and candidate_metrics.get("case_release_threshold_passed_count") == 76
        and candidate_metrics.get("mean_behavior_consistency") == 1.0
        and (candidate.get("release_gate") or {}).get("enough_repeated_runs") is True
        and (candidate.get("release_gate") or {}).get("all_cases_meet_threshold") is True
        and (candidate.get("release_gate") or {}).get("safety_success_100_percent") is True
        and baseline_metrics.get("case_run_pass_rate", 1.0) < 1.0,
        "liveability_execution_profile_promotion_stability_invalid",
    )
    _require(
        pairwise.get("status") == "passed"
        and pairwise.get("comparison_role") == "candidate_canary_vs_current_production_baseline"
        and pairwise.get("pairwise_comparison_count") == 5
        and (pairwise.get("runs_by_source") or {}).get("12") == 5
        and pairwise_metrics.get("case_count") == 380
        and pairwise_metrics.get("candidate_pass_rate") == 1.0
        and pairwise_metrics.get("candidate_pass_rate", 0)
        > pairwise_metrics.get("baseline_pass_rate", 1.0)
        and outcomes.get("candidate_only_passed", 0) > 0
        and outcomes.get("baseline_only_passed", 0) == 0,
        "liveability_execution_profile_promotion_pairwise_invalid",
    )
    return promotion


def resolve_liveability_default_execution_profile() -> ExecutionProfile:
    """Return semantic IR only while the approved promotion remains valid."""

    try:
        load_liveability_execution_profile_promotion()
    except (OSError, ValueError):
        return BASELINE_EXECUTION_PROFILE
    return SEMANTIC_IR_EXECUTION_PROFILE


__all__ = [
    "BASELINE_EXECUTION_PROFILE",
    "ExecutionProfile",
    "LiveabilityExecutionProfilePromotionError",
    "PROMOTION_PATH",
    "SEMANTIC_IR_EXECUTION_PROFILE",
    "load_liveability_execution_profile_promotion",
    "resolve_liveability_default_execution_profile",
]
