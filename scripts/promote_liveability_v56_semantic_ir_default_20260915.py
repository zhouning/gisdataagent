#!/usr/bin/env python3
"""Publish a narrow, evidence-bound Liveability semantic-IR default decision."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "docs/customer/abu_dhabi_liveability_site_validation"
CURRENT_BUNDLE = ARTIFACT_ROOT / "abu_dhabi_current_artifact_bundle.json"
CANDIDATE_STABILITY = (
    ARTIFACT_ROOT / "gpt56terra_online_liveability_v56_stability_full76_20260915.json"
)
BASELINE_STABILITY = (
    ARTIFACT_ROOT / "gpt56terra_online_liveability_v56_baseline_stability_full76_20260915.json"
)
PAIRWISE_STABILITY = (
    ARTIFACT_ROOT / "gpt56terra_online_liveability_v56_pairwise_stability_20260915.json"
)
OUTPUT = ARTIFACT_ROOT / "liveability_v56_semantic_ir_default_promotion_20260915.json"
RELEASE_ID = "liveability-v56-semantic-ir-default-20260915"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path, *, schema: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        raise RuntimeError(f"release_evidence_schema_invalid:{path.name}")
    return payload


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _descriptor(path: Path) -> dict[str, str]:
    return {"path": _relative(path), "sha256": _sha256(path)}


def _same(left: Any, right: Any, label: str) -> None:
    if left != right:
        raise RuntimeError(f"release_evidence_mismatch:{label}")


def _assert_candidate(candidate: dict[str, Any]) -> None:
    benchmark = candidate.get("benchmark") or {}
    metrics = candidate.get("metrics") or {}
    release_gate = candidate.get("release_gate") or {}
    if candidate.get("status") != "candidate_stability_ready":
        raise RuntimeError("candidate_stability_not_ready")
    if benchmark.get("execution_profile") != "semantic_ir_experimental":
        raise RuntimeError("candidate_profile_invalid")
    if (
        metrics.get("case_count") != 76
        or metrics.get("case_run_count") != 380
        or metrics.get("case_run_pass_rate") != 1.0
        or metrics.get("safety_pass_rate") != 1.0
        or metrics.get("case_release_threshold_passed_count") != 76
        or metrics.get("mean_behavior_consistency") != 1.0
        or release_gate.get("enough_repeated_runs") is not True
        or release_gate.get("all_cases_meet_threshold") is not True
        or release_gate.get("safety_success_100_percent") is not True
    ):
        raise RuntimeError("candidate_release_criteria_not_met")


def _assert_baseline(baseline: dict[str, Any]) -> None:
    benchmark = baseline.get("benchmark") or {}
    metrics = baseline.get("metrics") or {}
    if baseline.get("status") != "not_release_ready":
        raise RuntimeError("baseline_status_unexpected")
    if benchmark.get("execution_profile") != "baseline_sql":
        raise RuntimeError("baseline_profile_invalid")
    if metrics.get("case_count") != 76 or metrics.get("case_run_count") != 380:
        raise RuntimeError("baseline_coverage_invalid")


def _assert_pairwise(pairwise: dict[str, Any]) -> None:
    metrics = (pairwise.get("metrics") or {}).get("all_matched_observations") or {}
    outcomes = metrics.get("outcome_counts") or {}
    if (
        pairwise.get("status") != "passed"
        or pairwise.get("comparison_role") != "candidate_canary_vs_current_production_baseline"
        or pairwise.get("pairwise_comparison_count") != 5
        or (pairwise.get("runs_by_source") or {}).get("12") != 5
        or metrics.get("case_count") != 380
        or metrics.get("candidate_pass_rate") != 1.0
        or not isinstance(metrics.get("baseline_pass_rate"), (int, float))
        or metrics["candidate_pass_rate"] <= metrics["baseline_pass_rate"]
        or outcomes.get("candidate_only_passed", 0) <= 0
        or outcomes.get("baseline_only_passed", 0) != 0
    ):
        raise RuntimeError("pairwise_release_criteria_not_met")


def publish() -> dict[str, Any]:
    if OUTPUT.exists():
        raise RuntimeError("immutable_release_already_published")

    bundle = _load(CURRENT_BUNDLE, schema="gda.abu-dhabi-artifact-bundle.v1")
    candidate = _load(CANDIDATE_STABILITY, schema="gda.product-nl2sql-stability-report.v1")
    baseline = _load(BASELINE_STABILITY, schema="gda.product-nl2sql-stability-report.v1")
    pairwise = _load(PAIRWISE_STABILITY, schema="gda.nl2semantic2sql-pairwise-stability-comparison.v1")
    _assert_candidate(candidate)
    _assert_baseline(baseline)
    _assert_pairwise(pairwise)

    source = bundle.get("source") or {}
    semantic = (bundle.get("artifacts") or {}).get("semantic") or {}
    candidate_benchmark = candidate.get("benchmark") or {}
    baseline_benchmark = baseline.get("benchmark") or {}
    for key in (
        "source_id",
        "discovery_fingerprint",
        "semantic_layer_version",
        "metric_contract_version",
    ):
        _same(candidate_benchmark.get(key), baseline_benchmark.get(key), f"benchmark.{key}")
    _same(source.get("source_id"), 12, "bundle.source_id")
    _same(candidate_benchmark.get("source_id"), source.get("source_id"), "source_id")
    _same(
        candidate_benchmark.get("discovery_fingerprint"),
        source.get("discovery_fingerprint"),
        "discovery_fingerprint",
    )
    _same(
        candidate_benchmark.get("semantic_layer_version"),
        bundle.get("semantic_version"),
        "semantic_version",
    )
    if not semantic.get("path") or not semantic.get("sha256"):
        raise RuntimeError("current_semantic_descriptor_missing")

    pairwise_metrics = (pairwise.get("metrics") or {}).get("all_matched_observations") or {}
    candidate_metrics = candidate.get("metrics") or {}
    baseline_metrics = baseline.get("metrics") or {}
    promotion = {
        "schema": "gda.liveability-execution-profile-promotion.v1",
        "release_id": RELEASE_ID,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "approved",
        "authorization": {
            "source_id": 12,
            "source_database": source.get("database_name"),
            "source_discovery_fingerprint": source.get("discovery_fingerprint"),
            "default_execution_profile": "semantic_ir_experimental",
            "rollback_execution_profile": "baseline_sql",
            "scope": "Liveability registered source only; Makani and federated routes excluded",
            "model_requested": candidate_benchmark.get("model_requested"),
            "reasoning_effort": candidate_benchmark.get("reasoning_effort"),
        },
        "semantic_artifact": {
            "path": semantic.get("path"),
            "sha256": semantic.get("sha256"),
            "semantic_version": bundle.get("semantic_version"),
            "ontology_version": bundle.get("ontology_version"),
            "artifact_bundle_id": bundle.get("artifact_bundle_id"),
        },
        "evidence": {
            "current_artifact_bundle": _descriptor(CURRENT_BUNDLE),
            "candidate_stability": _descriptor(CANDIDATE_STABILITY),
            "baseline_stability": _descriptor(BASELINE_STABILITY),
            "pairwise_stability": _descriptor(PAIRWISE_STABILITY),
        },
        "evidence_summary": {
            "benchmark_id": candidate_benchmark.get("benchmark_id"),
            "benchmark_case_count": candidate_metrics.get("case_count"),
            "repeated_run_count": 5,
            "candidate_case_run_count": candidate_metrics.get("case_run_count"),
            "candidate_case_run_pass_rate": candidate_metrics.get("case_run_pass_rate"),
            "candidate_safety_pass_rate": candidate_metrics.get("safety_pass_rate"),
            "baseline_case_run_pass_rate": baseline_metrics.get("case_run_pass_rate"),
            "candidate_only_passed_observation_count": (
                (pairwise_metrics.get("outcome_counts") or {}).get("candidate_only_passed")
            ),
            "baseline_only_passed_observation_count": (
                (pairwise_metrics.get("outcome_counts") or {}).get("baseline_only_passed")
            ),
            "paired_generation_latency_tradeoff": {
                "candidate_minus_baseline_mean_generation_latency_ms": (
                    (pairwise_metrics.get("paired_generation") or {}).get(
                        "candidate_minus_baseline_mean_generation_latency_ms"
                    )
                ),
                "candidate_p95_generation_latency_ms": (
                    (pairwise_metrics.get("paired_generation") or {}).get(
                        "candidate_p95_generation_latency_ms"
                    )
                ),
            },
        },
        "claim_boundary": {
            "runtime_uses_benchmark_gold": False,
            "runtime_uses_model_outputs": False,
            "source_rows_persisted": False,
            "promotion_is_full_arbitrary_question_coverage": False,
            "business_ontology_complete": False,
            "rollback_requires_internal_operator_or_deployment_configuration": True,
            "pairwise_aggregator_authorizes_promotion": False,
        },
        "limitations": [
            "The default is authorized only for Liveability source 12 with the recorded model, semantic artifact, and source fingerprint.",
            "The 76-case benchmark and five repeated runs do not establish coverage for arbitrary customer questions or a complete business ontology.",
            "Semantic IR has higher evaluated latency than baseline; the baseline profile remains the rollback path.",
        ],
    }
    OUTPUT.write_text(json.dumps(promotion, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return promotion


if __name__ == "__main__":
    released = publish()
    print(json.dumps({"status": released["status"], "output": _relative(OUTPUT)}))
