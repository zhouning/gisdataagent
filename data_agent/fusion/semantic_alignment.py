"""Reusable semantic alignment scoring for MMFE."""

from __future__ import annotations

from typing import Any


DEFAULT_ALIGNMENT_SCORING_WEIGHTS = {
    "matcher_confidence": 0.65,
    "dtype_compatibility": 0.20,
    "value_profile_support": 0.10,
    "ontology_support": 0.05,
    "document_context_support": 0.10,
}


def score_semantic_alignment(
    confidence: Any,
    match_type: str,
    evidence: list[dict],
    weights: dict[str, float] | None = None,
) -> dict:
    """Score a semantic field alignment from matcher confidence and evidence."""
    active_weights = {**DEFAULT_ALIGNMENT_SCORING_WEIGHTS, **(weights or {})}
    components = {
        "matcher_confidence": _confidence_value(confidence),
        "dtype_compatibility": _dtype_evidence_score(evidence),
        "value_profile_support": _has_evidence(evidence, "value_profile"),
        "ontology_support": 1.0 if match_type == "ontology" else 0.0,
        "document_context_support": _document_context_evidence_score(evidence),
    }

    score = 0.0
    for name, value in components.items():
        score += value * active_weights.get(name, 0.0)
    score = round(min(max(score, 0.0), 1.0), 4)

    return {
        "score": score,
        "decision": alignment_decision(score),
        "components": components,
        "weights": active_weights,
    }


def build_alignment_summary(semantic_mappings: list[dict]) -> dict:
    """Summarize semantic mapping decisions for AI metadata and QA routing."""
    decisions = {"accept": 0, "review": 0, "reject": 0}
    for mapping in semantic_mappings:
        decision = mapping.get("alignment_score", {}).get("decision", "review")
        if decision not in decisions:
            decision = "review"
        decisions[decision] += 1
    return {
        "total_mappings": len(semantic_mappings),
        "decisions": decisions,
    }


def alignment_decision(score: float) -> str:
    """Convert a normalized alignment score to an operational decision."""
    if score >= 0.8:
        return "accept"
    if score >= 0.6:
        return "review"
    return "reject"


def _confidence_value(confidence: Any) -> float:
    try:
        return round(min(max(float(confidence), 0.0), 1.0), 4)
    except (TypeError, ValueError):
        return 0.0


def _dtype_evidence_score(evidence: list[dict]) -> float:
    for item in evidence:
        if item.get("type") == "dtype":
            return 1.0 if item.get("compatible", True) else 0.0
    return 0.5


def _has_evidence(evidence: list[dict], evidence_type: str) -> float:
    return 1.0 if any(item.get("type") == evidence_type for item in evidence) else 0.5


def _document_context_evidence_score(evidence: list[dict]) -> float:
    scores = []
    for item in evidence:
        if item.get("type") != "document_context":
            continue
        try:
            support = float(item.get("support", 1.0))
        except (TypeError, ValueError):
            support = 1.0
        scores.append(min(max(support, 0.0), 1.0))
    return max(scores) if scores else 0.0
