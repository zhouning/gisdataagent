"""Reusable semantic alignment scoring for MMFE."""

from __future__ import annotations

import json
from typing import Any


DEFAULT_ALIGNMENT_SCORING_WEIGHTS = {
    "matcher_confidence": 0.65,
    "dtype_compatibility": 0.20,
    "value_profile_support": 0.10,
    "ontology_support": 0.05,
    "document_context_support": 0.10,
}

STANDARD_GROUNDED_MATCH_TYPES = {
    "ontology",
    "standard_alias",
    "standard_field_catalog",
    "standard_role_contract",
    "standard_contract",
    "twm_binding",
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
        "value_profile_support": _value_profile_support_score(evidence),
        "ontology_support": _ontology_or_standard_support(match_type, evidence),
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


def build_standard_field_catalog(
    standard_fields: Any = None,
    field_aliases: Any = None,
) -> dict[str, dict]:
    """Build a field-code keyed standard catalog from rows and alias assets."""
    catalog: dict[str, dict] = {}
    for row in _standard_field_rows(standard_fields):
        field = _first_text(
            row.get("field_name"),
            row.get("name"),
            row.get("code"),
            row.get("field"),
        )
        if not field:
            continue
        normalized = dict(row)
        normalized.setdefault("field_name", field)
        catalog[field] = normalized

    for field, alias in _extract_field_aliases(field_aliases).items():
        entry = catalog.setdefault(field, {"field_name": field})
        if alias and not entry.get("field_alias_zh"):
            entry["field_alias_zh"] = alias
    return catalog


def align_layer_fields_to_standard_contract(
    fields: list[str],
    standard_role: str,
    role_contracts: Any,
    field_aliases: Any = None,
    standard_fields: Any = None,
    value_domains: Any = None,
    *,
    layer_role: str = "",
    object_type: str = "",
    field_alias_overrides: dict[str, str] | None = None,
) -> list[dict]:
    """Align observed layer fields to a role contract and standard catalog.

    The result is intentionally plain JSON-compatible data so scripts, tools and
    API layers can carry the same evidence without importing geospatial runtimes.
    """
    catalog = build_standard_field_catalog(standard_fields, field_aliases)
    aliases = _extract_field_aliases(field_aliases)
    domains = _extract_value_domains(value_domains)
    roles = _extract_roles(role_contracts)
    standard_meta = _standard_metadata(role_contracts)
    overrides = field_alias_overrides or {}
    return [
        align_field_to_standard_contract(
            field,
            standard_role,
            roles.get(standard_role, {}),
            aliases,
            catalog,
            domains,
            standard_meta=standard_meta,
            layer_role=layer_role,
            object_type=object_type,
            source_alias=overrides.get(field, ""),
        )
        for field in fields
    ]


def align_field_to_standard_contract(
    source_field: str,
    standard_role: str,
    role_contract: dict,
    field_aliases: dict[str, str],
    standard_catalog: dict[str, dict],
    value_domains: dict[str, list[dict]],
    *,
    standard_meta: dict | None = None,
    layer_role: str = "",
    object_type: str = "",
    source_alias: str = "",
) -> dict:
    """Align one observed field to the most plausible standard field."""
    standard_meta = standard_meta or {}
    resolved = _resolve_standard_field(
        source_field,
        source_alias,
        standard_role,
        role_contract,
        field_aliases,
        standard_catalog,
    )
    standard_field = resolved["standard_field"]
    catalog = standard_catalog.get(standard_field, {}) if standard_field else {}
    required = set(role_contract.get("required_fields") or [])
    recommended = set(role_contract.get("recommended_fields") or [])
    field_rules = role_contract.get("field_rules") or {}
    rule = field_rules.get(standard_field, {}) if standard_field else {}
    twm_key = _semantic_key_for_field(role_contract, standard_field)
    domain_code = str(rule.get("domain") or "")
    value_domain_status = _value_domain_status(domain_code, value_domains)
    standard_reference = _build_standard_reference(
        standard_role,
        role_contract,
        catalog,
        standard_meta,
    )
    requirement = _contract_requirement(standard_field, required, recommended)
    match_type = _standard_match_type(resolved, catalog)
    confidence = _standard_alignment_confidence(
        resolved,
        requirement,
        bool(catalog),
        bool(role_contract),
        bool(rule),
        bool(twm_key),
    )
    evidence = _standard_alignment_evidence(
        source_field=source_field,
        source_alias=source_alias,
        standard_field=standard_field,
        standard_role=standard_role,
        role_contract=role_contract,
        catalog=catalog,
        field_aliases=field_aliases,
        requirement=requirement,
        rule=rule,
        domain_code=domain_code,
        value_domains=value_domains,
        twm_key=twm_key,
        resolved=resolved,
        standard_reference=standard_reference,
    )
    alignment_score = score_semantic_alignment(confidence, match_type, evidence)
    return {
        "layer_role": layer_role,
        "standard_role": standard_role,
        "object_type": object_type,
        "source_field": source_field,
        "field_name": source_field,
        "source_alias_zh": source_alias,
        "target_field": f"{standard_role}.{standard_field}" if standard_field else "",
        "standard_field": standard_field,
        "field_alias_zh": (
            field_aliases.get(standard_field)
            or catalog.get("field_alias_zh")
            or source_alias
            or ""
        ),
        "standard_version": (
            catalog.get("standard_version")
            or standard_meta.get("version")
            or standard_meta.get("standard_version")
            or ""
        ),
        "lifecycle_status": catalog.get("lifecycle_status") or (
            "not_in_standard_catalog" if not catalog else ""
        ),
        "contract_requirement": requirement,
        "twm_semantic_key": twm_key,
        "domain_or_rule": rule,
        "value_domain": domain_code,
        "value_domain_status": value_domain_status,
        "match_type": match_type,
        "alignment_match_type": resolved["basis"],
        "confidence": confidence,
        "confidence_band": _confidence_band(confidence),
        "evidence": evidence,
        "standard_reference": standard_reference,
        "alignment_score": alignment_score,
        "alignment_decision": alignment_score["decision"],
        "requires_review": alignment_score["decision"] != "accept",
        "explanation": _standard_alignment_explanation(
            source_field,
            standard_field,
            standard_role,
            match_type,
            confidence,
            evidence,
        ),
    }


def build_standard_alignment_summary(alignments: list[dict]) -> dict:
    """Summarize standard-grounded field alignment readiness."""
    summary_inputs = []
    for item in alignments:
        score = item.get("alignment_score", {})
        if isinstance(score, dict):
            summary_inputs.append({"alignment_score": score})
        else:
            summary_inputs.append({
                "alignment_score": {
                    "score": score,
                    "decision": item.get("alignment_decision", "review"),
                }
            })
    summary = build_alignment_summary(summary_inputs)
    match_counter: dict[str, int] = {}
    requirement_counter: dict[str, int] = {}
    missing_value_domains: dict[str, int] = {}
    loaded_value_domains: dict[str, int] = {}
    for item in alignments:
        match = item.get("match_type") or "unknown"
        requirement = item.get("contract_requirement") or "unknown"
        match_counter[match] = match_counter.get(match, 0) + 1
        requirement_counter[requirement] = requirement_counter.get(requirement, 0) + 1
        for evidence in _alignment_evidence(item):
            if evidence.get("type") != "value_domain":
                continue
            domain = str(evidence.get("domain") or "")
            if not domain:
                continue
            if evidence.get("domain_known") is False:
                missing_value_domains[domain] = missing_value_domains.get(domain, 0) + 1
            else:
                loaded_value_domains[domain] = loaded_value_domains.get(domain, 0) + 1
    summary.update({
        "match_type_distribution": match_counter,
        "requirement_distribution": requirement_counter,
        "review_required": summary["decisions"]["review"] + summary["decisions"]["reject"],
        "missing_value_domains": missing_value_domains,
        "loaded_value_domains": loaded_value_domains,
    })
    return summary


def build_value_domain_catalog(value_domains: Any) -> dict[str, dict]:
    """Normalize value-domain payloads into domain metadata and item maps."""
    raw_domains = _extract_value_domains(value_domains)
    catalog: dict[str, dict] = {}
    for domain_code, items in raw_domains.items():
        item_map: dict[str, dict] = {}
        aliases: dict[str, str] = {}
        for item in items:
            code = _first_text(
                item.get("code"),
                item.get("value"),
                item.get("id"),
                item.get("name"),
            )
            if not code:
                continue
            normalized = dict(item)
            normalized.setdefault("code", code)
            item_map[code] = normalized
            name = _first_text(
                item.get("name_zh"),
                item.get("label_zh"),
                item.get("name"),
                item.get("label"),
            )
            if name:
                aliases[code] = name
        catalog[domain_code] = {
            "domain": domain_code,
            "item_count": len(item_map),
            "items": item_map,
            "aliases": aliases,
            "known": bool(item_map),
        }
    return catalog


def audit_field_value_domain(
    values: list[Any],
    domain_code: str,
    value_domains: Any,
    *,
    layer_role: str = "",
    field_name: str = "",
    max_unknown_values: int = 20,
) -> dict:
    """Audit observed field values against a standard value domain."""
    catalog = build_value_domain_catalog(value_domains)
    domain = catalog.get(domain_code)
    normalized_values = [_normalize_domain_value(value) for value in values]
    non_null_values = [value for value in normalized_values if value != ""]
    observed_counts: dict[str, int] = {}
    for value in non_null_values:
        observed_counts[value] = observed_counts.get(value, 0) + 1

    if not domain or not domain.get("known"):
        status = "domain_missing"
        known_codes: set[str] = set()
    else:
        known_codes = set(domain["items"])
        unknown_codes = sorted(code for code in observed_counts if code not in known_codes)
        if unknown_codes:
            status = "has_unknown_values"
        else:
            status = "valid"

    unknown_values = sorted(code for code in observed_counts if code not in known_codes)
    valid_count = sum(count for code, count in observed_counts.items() if code in known_codes)
    unknown_count = sum(count for code, count in observed_counts.items() if code not in known_codes)
    null_count = len(normalized_values) - len(non_null_values)
    total_count = len(normalized_values)
    non_null_count = len(non_null_values)
    coverage = round(valid_count / non_null_count, 6) if non_null_count else 1.0
    return {
        "layer_role": layer_role,
        "field_name": field_name,
        "domain": domain_code,
        "domain_status": "loaded" if domain and domain.get("known") else "referenced_missing_items",
        "audit_status": status,
        "domain_item_count": len(known_codes),
        "total_count": total_count,
        "non_null_count": non_null_count,
        "null_count": null_count,
        "distinct_observed_count": len(observed_counts),
        "valid_count": valid_count,
        "unknown_count": unknown_count,
        "coverage": coverage,
        "observed_values": [
            {"code": code, "count": count, "name_zh": (domain or {}).get("aliases", {}).get(code, "")}
            for code, count in sorted(observed_counts.items())
        ],
        "unknown_values": [
            {"code": code, "count": observed_counts[code]}
            for code in unknown_values[:max_unknown_values]
        ],
        "unknown_values_truncated": len(unknown_values) > max_unknown_values,
    }


def build_value_domain_audit_summary(audit_rows: list[dict]) -> dict:
    """Summarize observed value-domain audit rows."""
    status_counter: dict[str, int] = {}
    domain_counter: dict[str, int] = {}
    invalid_rows = []
    for row in audit_rows:
        status = row.get("audit_status") or "unknown"
        domain = row.get("domain") or ""
        status_counter[status] = status_counter.get(status, 0) + 1
        if domain:
            domain_counter[domain] = domain_counter.get(domain, 0) + 1
        if status not in {"valid"}:
            invalid_rows.append(row)
    return {
        "audit_count": len(audit_rows),
        "status_distribution": status_counter,
        "domain_distribution": domain_counter,
        "requires_review_count": len(invalid_rows),
        "top_review_items": [
            {
                "layer_role": row.get("layer_role"),
                "field_name": row.get("field_name"),
                "domain": row.get("domain"),
                "audit_status": row.get("audit_status"),
                "unknown_count": row.get("unknown_count"),
                "coverage": row.get("coverage"),
            }
            for row in invalid_rows[:10]
        ],
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


def _has_evidence(evidence: list[dict], evidence_type: Any) -> float:
    if isinstance(evidence_type, str):
        evidence_types = {evidence_type}
    else:
        evidence_types = set(evidence_type)
    return 1.0 if any(item.get("type") in evidence_types for item in evidence) else 0.5


def _value_profile_support_score(evidence: list[dict]) -> float:
    score = 0.5
    for item in evidence:
        evidence_type = item.get("type")
        if evidence_type == "value_domain":
            if item.get("domain_known") is False:
                score = max(score, 0.5)
            else:
                score = 1.0
        elif evidence_type in {"value_profile", "format_rule", "field_rule"}:
            score = 1.0
    return score


def _ontology_or_standard_support(match_type: str, evidence: list[dict]) -> float:
    if match_type in STANDARD_GROUNDED_MATCH_TYPES:
        return 1.0
    standard_evidence = {
        "standard_catalog",
        "role_contract",
        "standard_reference",
        "field_alias",
        "twm_binding",
    }
    if any(item.get("type") in standard_evidence for item in evidence):
        return 1.0
    return 0.0


def _alignment_evidence(item: dict) -> list[dict]:
    evidence = item.get("evidence")
    if isinstance(evidence, list):
        return [entry for entry in evidence if isinstance(entry, dict)]
    evidence_json = item.get("evidence_json")
    if isinstance(evidence_json, str):
        try:
            parsed = json.loads(evidence_json)
        except Exception:
            return []
        if isinstance(parsed, list):
            return [entry for entry in parsed if isinstance(entry, dict)]
    return []


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


def _standard_field_rows(standard_fields: Any) -> list[dict]:
    if not standard_fields:
        return []
    if isinstance(standard_fields, list):
        return [row for row in standard_fields if isinstance(row, dict)]
    if isinstance(standard_fields, dict):
        for key in ("fields", "standard_fields", "items"):
            rows = standard_fields.get(key)
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        rows = []
        for key, value in standard_fields.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("field_name", key)
                rows.append(row)
        return rows
    return []


def _extract_field_aliases(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    aliases = payload.get("field_aliases")
    if isinstance(aliases, dict):
        return {str(k): str(v) for k, v in aliases.items() if k and v}
    return {
        str(k): str(v)
        for k, v in payload.items()
        if isinstance(v, str) and k and v
    }


def _extract_value_domains(payload: Any) -> dict[str, list[dict]]:
    if not isinstance(payload, dict):
        return {}
    domains = payload.get("domains", payload)
    if not isinstance(domains, dict):
        return {}
    normalized: dict[str, list[dict]] = {}
    for key, values in domains.items():
        if isinstance(values, list):
            normalized[str(key)] = [
                dict(item) if isinstance(item, dict) else {"code": str(item)}
                for item in values
            ]
    return normalized


def _extract_roles(payload: Any) -> dict[str, dict]:
    if not isinstance(payload, dict):
        return {}
    roles = payload.get("roles")
    if isinstance(roles, dict):
        return {str(k): v for k, v in roles.items() if isinstance(v, dict)}
    return {str(k): v for k, v in payload.items() if isinstance(v, dict)}


def _standard_metadata(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {}
    return {
        "standard_id": payload.get("standard_id", ""),
        "standard_name_zh": payload.get("standard_name_zh", ""),
        "version": payload.get("version", ""),
        "status": payload.get("status", ""),
        "source_documents": list(payload.get("source_documents") or [])[:8],
    }


def _resolve_standard_field(
    source_field: str,
    source_alias: str,
    standard_role: str,
    role_contract: dict,
    field_aliases: dict[str, str],
    standard_catalog: dict[str, dict],
) -> dict:
    source = str(source_field or "").strip()
    alias = str(source_alias or "").strip()
    role_fields = _role_fields(role_contract)
    candidate_order: list[str] = []

    if source in role_fields:
        candidate_order.append(source)
        basis = "exact_role_contract"
    elif source in standard_catalog:
        candidate_order.append(source)
        basis = "exact_standard_catalog"
    else:
        basis = "unmatched"

    alias_candidates = [
        field for field, field_alias in field_aliases.items()
        if _same_text(source, field_alias) or (alias and _same_text(alias, field_alias))
    ]
    if alias_candidates:
        role_alias_candidates = [field for field in alias_candidates if field in role_fields]
        candidates = role_alias_candidates or alias_candidates
        candidate_order.extend([field for field in candidates if field not in candidate_order])
        if basis == "unmatched":
            basis = "alias_role_contract" if role_alias_candidates else "alias_standard_catalog"

    if not candidate_order:
        return {
            "standard_field": "",
            "basis": "local_extension",
            "ambiguous": False,
            "candidates": [],
        }

    candidates = candidate_order
    if len(candidates) > 1:
        role_candidates = [field for field in candidates if field in role_fields]
        if len(role_candidates) == 1:
            selected = role_candidates[0]
            ambiguous = False
        else:
            selected = candidates[0]
            ambiguous = True
    else:
        selected = candidates[0]
        ambiguous = False

    return {
        "standard_field": selected,
        "basis": basis,
        "ambiguous": ambiguous,
        "candidates": candidates,
        "standard_role": standard_role,
    }


def _role_fields(role_contract: dict) -> set[str]:
    return set(role_contract.get("required_fields") or []) | set(
        role_contract.get("recommended_fields") or []
    ) | set((role_contract.get("field_rules") or {}).keys()) | set(
        (role_contract.get("twm_binding") or {}).values()
    )


def _semantic_key_for_field(role_contract: dict, standard_field: str) -> str:
    if not standard_field:
        return ""
    for key, field in (role_contract.get("twm_binding") or {}).items():
        if field == standard_field:
            return str(key)
    return ""


def _contract_requirement(
    standard_field: str,
    required: set[str],
    recommended: set[str],
) -> str:
    if not standard_field:
        return "local_extension"
    if standard_field in required:
        return "required"
    if standard_field in recommended:
        return "recommended"
    return "observed"


def _standard_match_type(resolved: dict, catalog: dict) -> str:
    basis = resolved.get("basis")
    if basis in {"alias_role_contract", "alias_standard_catalog"}:
        return "standard_alias"
    if basis == "exact_role_contract":
        return "standard_field_catalog" if catalog else "standard_role_contract"
    if basis == "exact_standard_catalog":
        return "standard_field_catalog"
    return "local_extension"


def _standard_alignment_confidence(
    resolved: dict,
    requirement: str,
    in_catalog: bool,
    has_role_contract: bool,
    has_rule: bool,
    has_twm_key: bool,
) -> float:
    basis = resolved.get("basis")
    if basis == "local_extension":
        return 0.72
    if basis in {"alias_role_contract", "alias_standard_catalog"}:
        confidence = 0.92
    elif basis == "exact_role_contract":
        confidence = 0.97 if requirement == "required" else 0.95
    elif basis == "exact_standard_catalog":
        confidence = 0.90
    else:
        confidence = 0.72

    if in_catalog:
        confidence += 0.02
    if has_rule:
        confidence += 0.01
    if has_twm_key:
        confidence += 0.01
    if not has_role_contract and basis != "exact_standard_catalog":
        confidence -= 0.05
    if resolved.get("ambiguous"):
        confidence -= 0.18
    return round(min(max(confidence, 0.0), 0.99), 4)


def _standard_alignment_evidence(
    *,
    source_field: str,
    source_alias: str,
    standard_field: str,
    standard_role: str,
    role_contract: dict,
    catalog: dict,
    field_aliases: dict[str, str],
    requirement: str,
    rule: dict,
    domain_code: str,
    value_domains: dict[str, list[dict]],
    twm_key: str,
    resolved: dict,
    standard_reference: dict,
) -> list[dict]:
    evidence: list[dict] = []
    if standard_field:
        evidence.append({
            "type": "matcher",
            "detail": f"{source_field} matched standard field {standard_field}",
            "basis": resolved.get("basis", ""),
        })
    else:
        evidence.append({
            "type": "local_extension",
            "detail": f"{source_field} is not present in the standard catalog or role contract",
        })

    if catalog:
        evidence.append({
            "type": "standard_catalog",
            "detail": f"{standard_field} exists in standard field catalog",
            "lifecycle_status": catalog.get("lifecycle_status", ""),
            "standard_version": catalog.get("standard_version", ""),
        })

    alias = field_aliases.get(standard_field) if standard_field else ""
    if alias:
        detail = f"{standard_field} alias is {alias}"
        if source_alias and _same_text(source_alias, alias):
            detail = f"source alias {source_alias} matches standard alias {alias}"
        evidence.append({
            "type": "field_alias",
            "detail": detail,
            "alias_zh": alias,
        })

    if role_contract:
        evidence.append({
            "type": "role_contract",
            "detail": f"{standard_role}.{standard_field or source_field} requirement={requirement}",
            "standard_role": standard_role,
            "role_alias_zh": role_contract.get("role_alias_zh", ""),
            "requirement": requirement,
        })

    if twm_key:
        evidence.append({
            "type": "twm_binding",
            "detail": f"{standard_field} binds TWM semantic key {twm_key}",
            "semantic_key": twm_key,
        })

    if domain_code:
        domain_items = value_domains.get(domain_code, [])
        evidence.append({
            "type": "value_domain",
            "detail": f"{standard_field} uses value domain {domain_code}",
            "domain": domain_code,
            "domain_item_count": len(domain_items),
            "domain_known": bool(domain_items),
        })
    elif rule:
        evidence.append({
            "type": "field_rule",
            "detail": f"{standard_field} has standard field rule",
            "rule": rule,
        })

    if resolved.get("ambiguous"):
        evidence.append({
            "type": "ambiguity",
            "detail": f"multiple candidate standard fields: {', '.join(resolved.get('candidates', []))}",
            "candidates": resolved.get("candidates", []),
        })

    if standard_reference.get("standard_id") or standard_reference.get("standard_tables"):
        evidence.append({
            "type": "standard_reference",
            "detail": f"defined by {standard_reference.get('standard_id') or 'role contract'}",
            "standard_id": standard_reference.get("standard_id", ""),
            "standard_version": standard_reference.get("standard_version", ""),
            "standard_tables": standard_reference.get("standard_tables", []),
        })
    return evidence


def _value_domain_status(domain_code: str, value_domains: dict[str, list[dict]]) -> str:
    if not domain_code:
        return ""
    if value_domains.get(domain_code):
        return "loaded"
    return "referenced_missing_items"


def _build_standard_reference(
    standard_role: str,
    role_contract: dict,
    catalog: dict,
    standard_meta: dict,
) -> dict:
    return {
        "standard_id": standard_meta.get("standard_id", ""),
        "standard_name_zh": standard_meta.get("standard_name_zh", ""),
        "standard_version": (
            standard_meta.get("version")
            or standard_meta.get("standard_version")
            or catalog.get("standard_version")
            or ""
        ),
        "standard_status": standard_meta.get("status", ""),
        "standard_role": standard_role,
        "role_alias_zh": role_contract.get("role_alias_zh", ""),
        "standard_tables": role_contract.get("standard_tables", []),
        "source_documents": standard_meta.get("source_documents", []),
    }


def _standard_alignment_explanation(
    source_field: str,
    standard_field: str,
    standard_role: str,
    match_type: str,
    confidence: float,
    evidence: list[dict],
) -> str:
    bits = [item.get("detail", "") for item in evidence if item.get("detail")]
    target = f"{standard_role}.{standard_field}" if standard_field else "local extension"
    return (
        f"{source_field} -> {target} matched by {match_type} "
        f"with confidence {confidence}. " + "; ".join(bits[:5])
    ).strip()


def _confidence_band(confidence: Any) -> str:
    value = _confidence_value(confidence)
    if value >= 0.8:
        return "high"
    if value >= 0.6:
        return "medium"
    return "low"


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _normalize_domain_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        try:
            numeric = float(text)
            if numeric.is_integer():
                return str(int(numeric))
        except ValueError:
            return text
    return text


def _same_text(left: Any, right: Any) -> bool:
    return str(left or "").strip().casefold() == str(right or "").strip().casefold()
