from __future__ import annotations

from typing import Any


ALLOWED_COMPARATORS = {"eq", "in", "gt", "gte", "lt", "lte", "exists"}
ALLOWED_SPATIAL_PREDICATES = {
    "intersects",
    "within",
    "contains",
    "touches",
    "distance_lt",
    "overlap_area_gt",
}


def validate_rule_body(rule_body: dict[str, Any] | None) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(rule_body, dict):
        return {"valid": False, "errors": ["rule_body must be an object"], "normalized": {}}

    version = str(rule_body.get("version", "")).strip()
    if version and version not in {"1.0", "1", "1.0.0"}:
        errors.append("version must be 1.0")

    subject = rule_body.get("subject")
    if not isinstance(subject, dict):
        errors.append("subject must be an object")
        subject = {}
    if not str(subject.get("object_type", "")).strip():
        errors.append("subject.object_type is required")

    constraint = rule_body.get("constraint")
    if not isinstance(constraint, dict):
        errors.append("constraint must be an object")
        constraint = {}
    if not str(constraint.get("target_role", "")).strip():
        errors.append("constraint.target_role is required")
    spatial_predicate = str(constraint.get("spatial_predicate", "")).strip()
    if spatial_predicate and spatial_predicate not in ALLOWED_SPATIAL_PREDICATES:
        errors.append(f"unsupported spatial_predicate: {spatial_predicate}")

    hit_when = rule_body.get("hit_when") or {}
    if not isinstance(hit_when, dict):
        errors.append("hit_when must be an object")
        hit_when = {}
    for metric_name, comparator in hit_when.items():
        if not isinstance(comparator, dict):
            errors.append(f"hit_when.{metric_name} must be an object")
            continue
        for op in comparator:
            if op not in ALLOWED_COMPARATORS:
                errors.append(f"hit_when.{metric_name}.{op} is not supported")

    evidence = rule_body.get("evidence") or {}
    if evidence and not isinstance(evidence, dict):
        errors.append("evidence must be an object")
        evidence = {}
    review = rule_body.get("review") or {}
    if review and not isinstance(review, dict):
        errors.append("review must be an object")
        review = {}

    normalized = {
        "version": version or "1.0",
        "subject": subject,
        "constraint": constraint,
        "metrics": list(rule_body.get("metrics") or []),
        "hit_when": hit_when,
        "evidence": evidence,
        "review": review,
        "scenario": rule_body.get("scenario") or {},
        "metadata": rule_body.get("metadata") or {},
    }
    return {"valid": not errors, "errors": errors, "normalized": normalized}


def normalize_rule_body(rule_body: dict[str, Any] | None) -> dict[str, Any]:
    result = validate_rule_body(rule_body)
    if not result["valid"]:
        raise ValueError("; ".join(result["errors"]))
    return result["normalized"]
