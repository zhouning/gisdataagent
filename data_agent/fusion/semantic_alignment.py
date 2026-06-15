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


def build_alignment_review_items(semantic_mappings: list[dict]) -> list[dict]:
    """Build actionable review items for non-accepted semantic alignments."""
    review_items = []
    for index, mapping in enumerate(semantic_mappings):
        alignment_score = mapping.get("alignment_score", {})
        decision = alignment_score.get("decision", "review")
        if decision == "accept":
            continue

        reason_codes = _review_reason_codes(mapping)
        review_items.append({
            "review_id": f"alignment-review:{index}",
            "severity": _review_severity(decision, reason_codes),
            "decision": decision,
            "score": alignment_score.get("score"),
            "source_field": mapping.get("source_field", ""),
            "target_field": mapping.get("target_field", ""),
            "confidence": mapping.get("confidence"),
            "match_type": mapping.get("match_type", ""),
            "reason_codes": reason_codes,
            "evidence_summary": _evidence_summary(mapping.get("evidence", [])),
            "suggested_action": _suggested_review_action(decision, reason_codes),
        })
    return review_items


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


def _review_reason_codes(mapping: dict) -> list[str]:
    alignment_score = mapping.get("alignment_score", {})
    components = alignment_score.get("components", {})
    evidence = mapping.get("evidence", [])
    reason_codes = []

    decision = alignment_score.get("decision")
    if decision not in ("accept", "review", "reject"):
        reason_codes.append("unknown_decision")

    try:
        score = float(alignment_score.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    if score < 0.6:
        reason_codes.append("low_alignment_score")

    try:
        confidence = float(mapping.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.6:
        reason_codes.append("low_matcher_confidence")
    elif confidence < 0.8:
        reason_codes.append("borderline_matcher_confidence")

    if components.get("dtype_compatibility") == 0.0 or any(
        item.get("type") == "dtype" and item.get("compatible") is False
        for item in evidence
    ):
        reason_codes.append("dtype_conflict")

    if components.get("document_context_support", 0.0) <= 0.0 and not any(
        item.get("type") == "document_context" for item in evidence
    ):
        reason_codes.append("missing_document_context")

    if not evidence:
        reason_codes.append("missing_evidence")

    return reason_codes or ["manual_review_required"]


def _review_severity(decision: str, reason_codes: list[str]) -> str:
    if decision == "reject" or "dtype_conflict" in reason_codes:
        return "high"
    if "low_alignment_score" in reason_codes:
        return "high"
    return "medium"


def _suggested_review_action(decision: str, reason_codes: list[str]) -> str:
    if decision == "reject" or "dtype_conflict" in reason_codes:
        return "remove_or_remap_field_alignment"
    if "missing_document_context" in reason_codes:
        return "verify_with_domain_dictionary"
    if "low_matcher_confidence" in reason_codes:
        return "run_llm_or_embedding_alignment"
    return "review_mapping_evidence"


def _evidence_summary(evidence: list[dict]) -> list[str]:
    summary = []
    for item in evidence[:5]:
        detail = item.get("detail")
        if detail:
            summary.append(str(detail))
        elif item.get("type"):
            summary.append(str(item["type"]))
    return summary
