from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Mapping
import unicodedata

from data_agent.uwm.traditional_livability_facility_dictionary import (
    compute_canonical_content_digest,
)


SCHEMA = "uwm.traditional_livability.s6_semantic_resolution.v1"
CONFIRMATION_SCHEMA = "uwm.traditional_livability.s6_human_confirmation.v1"

_INPUT_FIELDS = ("facility_name", "raw_facility_type", "use_description")
_INTERNAL_SUGGESTION_RULES = (
    {
        "rule_id": "internal.food_truck.v1",
        "terms": ("食品车", "餐车", "food truck"),
        "suggested_class_label": "流动餐饮服务设施",
    },
)


def _normalized_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized or None


def _normalized_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalized_inputs(
    facility_name: Any,
    raw_facility_type: Any,
    use_description: Any,
) -> dict[str, str | None]:
    return {
        "facility_name": _normalized_text(facility_name),
        "raw_facility_type": _normalized_text(raw_facility_type),
        "use_description": _normalized_text(use_description),
    }


def _digestable_raw_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return {"invalid_input_type": type(value).__name__}


def _dictionary_classes(dictionary: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(dictionary, Mapping):
        return {}
    classes = dictionary.get("classes")
    if not isinstance(classes, list):
        return {}
    result = {}
    for row in classes:
        if not isinstance(row, Mapping):
            continue
        class_id = _normalized_string(row.get("class_id"))
        if class_id is not None:
            result[class_id] = dict(row)
    return result


def _authoritative_records(
    dictionary: Mapping[str, Any],
    record_type: str,
) -> list[dict[str, Any]]:
    records = dictionary.get(record_type)
    if not isinstance(records, list):
        return []
    normalized = []
    value_field = "alias" if record_type == "aliases" else "keyword"
    for record in records:
        if not isinstance(record, Mapping):
            continue
        value = _normalized_text(record.get(value_field))
        class_id = _normalized_string(record.get("class_id"))
        source_reference = _normalized_string(record.get("source_reference"))
        if value and class_id and source_reference:
            normalized.append(
                {
                    "value": value,
                    "class_id": class_id,
                    "source_reference": source_reference,
                }
            )
    return normalized


def _candidate(
    *,
    class_id: str,
    class_record: Mapping[str, Any],
    match_method: str,
    confidence: str,
    dictionary_version: str | None,
    rule_version: str | None,
    human_confirmation_required: bool,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "standard_class_id": class_id,
        "standard_class_label": class_record.get("label"),
        "authority_level": "authoritative_dictionary",
        "match_method": match_method,
        "confidence": confidence,
        "dictionary_version": dictionary_version,
        "rule_version": rule_version,
        "human_confirmation_required": human_confirmation_required,
        "human_confirmed": False,
        "evidence": evidence,
    }


def _authoritative_matches(
    *,
    dictionary: Mapping[str, Any],
    classes: Mapping[str, Mapping[str, Any]],
    inputs: Mapping[str, str | None],
    record_type: str,
    dictionary_version: str | None,
) -> list[dict[str, Any]]:
    matches: dict[str, list[dict[str, Any]]] = {}
    is_alias = record_type == "aliases"
    for record in _authoritative_records(dictionary, record_type):
        class_id = record["class_id"]
        if class_id not in classes:
            continue
        for input_field in _INPUT_FIELDS:
            input_value = inputs[input_field]
            if not input_value:
                continue
            matched = input_value == record["value"] if is_alias else record["value"] in input_value
            if matched:
                matches.setdefault(class_id, []).append(
                    {
                        "input_field": input_field,
                        "matched_value": record["value"],
                        "source_reference": record["source_reference"],
                    }
                )
    match_method = "authoritative_alias_exact" if is_alias else "authoritative_keyword_controlled"
    confidence = "exact" if is_alias else "controlled_rule"
    return [
        _candidate(
            class_id=class_id,
            class_record=classes[class_id],
            match_method=match_method,
            confidence=confidence,
            dictionary_version=dictionary_version,
            rule_version=None,
            human_confirmation_required=False,
            evidence=sorted(
                evidence,
                key=lambda row: (
                    _INPUT_FIELDS.index(row["input_field"]),
                    row["matched_value"],
                    row["source_reference"],
                ),
            ),
        )
        for class_id, evidence in sorted(matches.items())
    ]


def _internal_suggestions(
    inputs: Mapping[str, str | None],
    dictionary_version: str | None,
) -> list[dict[str, Any]]:
    suggestions = []
    for rule in _INTERNAL_SUGGESTION_RULES:
        evidence = []
        for input_field in _INPUT_FIELDS:
            input_value = inputs[input_field]
            if not input_value:
                continue
            for term in rule["terms"]:
                normalized_term = _normalized_text(term)
                if normalized_term and normalized_term in input_value:
                    evidence.append(
                        {
                            "input_field": input_field,
                            "matched_value": normalized_term,
                            "internal_rule_id": rule["rule_id"],
                        }
                    )
        if evidence:
            suggestions.append(
                {
                    "standard_class_id": None,
                    "standard_class_label": rule["suggested_class_label"],
                    "authority_level": "internal_suggestion",
                    "match_method": "internal_keyword_rule",
                    "confidence": "weak_suggestion",
                    "dictionary_version": dictionary_version,
                    "rule_version": rule["rule_id"],
                    "human_confirmation_required": True,
                    "human_confirmed": False,
                    "evidence": evidence,
                }
            )
    return suggestions


def resolve_s6_facility_semantics(
    *,
    facility_name: Any,
    raw_facility_type: Any,
    use_description: Any,
    dictionary: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve facility semantics conservatively without model inference."""
    inputs = _normalized_inputs(facility_name, raw_facility_type, use_description)
    input_digest = compute_canonical_content_digest(
        {
            "facility_name": _digestable_raw_value(facility_name),
            "raw_facility_type": _digestable_raw_value(raw_facility_type),
            "use_description": _digestable_raw_value(use_description),
        }
    )
    dictionary_ready = isinstance(dictionary, Mapping) and dictionary.get("ready") is True
    dictionary_version = None
    dictionary_digest = None
    if isinstance(dictionary, Mapping):
        source_metadata = dictionary.get("source_metadata")
        if isinstance(source_metadata, Mapping):
            dictionary_version = _normalized_string(source_metadata.get("dictionary_version"))
        dictionary_digest = _normalized_string(dictionary.get("content_digest"))

    base = {
        "schema": SCHEMA,
        "resolution_status": "unresolved",
        "confirmed_standard_class_id": None,
        "candidates": [],
        "resolution_reasons": [],
        "original_input_digest": input_digest,
        "dictionary_version": dictionary_version,
        "dictionary_content_digest": dictionary_digest,
        "llm_used": False,
    }
    if not any(inputs.values()):
        return {**base, "resolution_reasons": ["facility_semantic_input_missing"]}

    if dictionary_ready:
        classes = _dictionary_classes(dictionary)
        alias_candidates = _authoritative_matches(
            dictionary=dictionary,
            classes=classes,
            inputs=inputs,
            record_type="aliases",
            dictionary_version=dictionary_version,
        )
        if len(alias_candidates) == 1:
            return {
                **base,
                "resolution_status": "authoritative_confirmed",
                "confirmed_standard_class_id": alias_candidates[0]["standard_class_id"],
                "candidates": alias_candidates,
                "resolution_reasons": ["single_authoritative_exact_alias_match"],
            }
        if len(alias_candidates) > 1:
            return {
                **base,
                "candidates": [
                    {**candidate, "human_confirmation_required": True}
                    for candidate in alias_candidates
                ],
                "resolution_reasons": ["ambiguous_authoritative_alias_matches"],
            }

        keyword_candidates = _authoritative_matches(
            dictionary=dictionary,
            classes=classes,
            inputs=inputs,
            record_type="keywords",
            dictionary_version=dictionary_version,
        )
        if len(keyword_candidates) == 1:
            return {
                **base,
                "resolution_status": "authoritative_confirmed",
                "confirmed_standard_class_id": keyword_candidates[0]["standard_class_id"],
                "candidates": keyword_candidates,
                "resolution_reasons": ["single_authoritative_controlled_keyword_match"],
            }
        if len(keyword_candidates) > 1:
            return {
                **base,
                "candidates": [
                    {**candidate, "human_confirmation_required": True}
                    for candidate in keyword_candidates
                ],
                "resolution_reasons": ["ambiguous_authoritative_keyword_matches"],
            }

    suggestions = _internal_suggestions(inputs, dictionary_version)
    if suggestions:
        return {
            **base,
            "resolution_status": "suggested_review_required",
            "candidates": suggestions,
            "resolution_reasons": ["internal_suggestion_requires_human_review"],
        }
    reason = "no_deterministic_semantic_match"
    if not dictionary_ready:
        reason = "authoritative_dictionary_unavailable_and_no_internal_suggestion"
    return {**base, "resolution_reasons": [reason]}


def _parse_confirmation_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _raw_input_digest(original_input: Mapping[str, Any]) -> str:
    return compute_canonical_content_digest(
        {
            field: _digestable_raw_value(original_input.get(field))
            for field in _INPUT_FIELDS
        }
    )


def _raw_input_audit_view(original_input: Any) -> dict[str, Any] | None:
    if not isinstance(original_input, Mapping):
        return None
    return {
        field: _digestable_raw_value(original_input.get(field))
        for field in _INPUT_FIELDS
    }


def _candidate_audit_view(candidate: Any) -> dict[str, Any] | None:
    if not isinstance(candidate, Mapping):
        return None
    evidence = candidate.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return None
    return {
        "standard_class_id": _normalized_string(candidate.get("standard_class_id")),
        "standard_class_label": _normalized_string(candidate.get("standard_class_label")),
        "authority_level": _normalized_string(candidate.get("authority_level")),
        "match_method": _normalized_string(candidate.get("match_method")),
        "confidence": _normalized_string(candidate.get("confidence")),
        "dictionary_version": _normalized_string(candidate.get("dictionary_version")),
        "rule_version": _normalized_string(candidate.get("rule_version")),
        "human_confirmation_required": candidate.get("human_confirmation_required"),
        "human_confirmed": candidate.get("human_confirmed") is True,
        "evidence": evidence,
    }


def _human_selected_candidate(
    candidate: dict[str, Any] | None,
    *,
    selected_class_id: str | None,
    classes: Mapping[str, Mapping[str, Any]],
    dictionary_version: str | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    if candidate is None or candidate.get("match_method") != "human_selected":
        return None, []
    errors = []
    if candidate.get("authority_level") != "human_confirmation":
        errors.append("human_selected_authority_level_invalid")
    if candidate.get("confidence") != "human_confirmed":
        errors.append("human_selected_confidence_invalid")
    if candidate.get("human_confirmed") is not True:
        errors.append("human_selected_confirmation_marker_missing")
    if candidate.get("human_confirmation_required") is not False:
        errors.append("human_selected_confirmation_state_invalid")
    candidate_class_id = candidate.get("standard_class_id")
    if candidate_class_id != selected_class_id:
        errors.append("selected_candidate_class_mismatch")
    if candidate_class_id not in classes:
        errors.append("selected_standard_class_not_in_dictionary")
    if candidate.get("dictionary_version") != dictionary_version:
        errors.append("selected_candidate_dictionary_version_mismatch")
    evidence = candidate.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append("selected_candidate_evidence_missing")
    elif not all(
        isinstance(row, Mapping)
        and _normalized_string(row.get("evidence_type")) is not None
        and _normalized_string(row.get("reason")) is not None
        for row in evidence
    ):
        errors.append("selected_candidate_reviewer_reason_missing")
    if errors:
        return None, errors
    class_record = classes[candidate_class_id]
    return {
        **candidate,
        "standard_class_label": class_record.get("label"),
        "authority_level": "human_confirmation",
        "match_method": "human_selected",
        "confidence": "human_confirmed",
        "dictionary_version": dictionary_version,
        "rule_version": None,
        "human_confirmation_required": False,
        "human_confirmed": True,
    }, []


def _current_resolution(
    original_input: Any,
    dictionary: Mapping[str, Any],
) -> tuple[dict[str, str | None] | None, str | None, dict[str, Any] | None]:
    if not isinstance(original_input, Mapping):
        return None, None, None
    normalized_input = _normalized_inputs(
        original_input.get("facility_name"),
        original_input.get("raw_facility_type"),
        original_input.get("use_description"),
    )
    digest = _raw_input_digest(original_input)
    resolution = resolve_s6_facility_semantics(
        facility_name=original_input.get("facility_name"),
        raw_facility_type=original_input.get("raw_facility_type"),
        use_description=original_input.get("use_description"),
        dictionary=dictionary,
    )
    return normalized_input, digest, resolution


def _semantically_complete_input(
    original_input: Any,
    normalized_input: Mapping[str, str | None] | None,
) -> bool:
    return (
        isinstance(original_input, Mapping)
        and normalized_input is not None
        and all(isinstance(original_input.get(field), str) for field in _INPUT_FIELDS)
        and all(normalized_input.get(field) is not None for field in _INPUT_FIELDS)
    )


def validate_human_confirmation(
    confirmation: Mapping[str, Any],
    *,
    dictionary: Mapping[str, Any],
    original_input: Mapping[str, Any] | None = None,
    selected_candidate: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate a human decision for one request without changing authority."""
    payload = confirmation if isinstance(confirmation, Mapping) else {}
    actor_id = _normalized_string(payload.get("actor_id"))
    confirmed_at = _normalized_string(payload.get("confirmed_at"))
    selected_class_id = _normalized_string(payload.get("selected_standard_class_id"))
    supplied_input_digest = _normalized_string(payload.get("original_input_digest"))
    supplied_dictionary_version = _normalized_string(payload.get("dictionary_version"))

    normalized_input, expected_input_digest, current_resolution = _current_resolution(
        original_input,
        dictionary,
    )
    supplied_candidate = _candidate_audit_view(selected_candidate)
    matched_candidate = None
    candidate_errors = []
    classes = _dictionary_classes(dictionary)
    source_metadata = dictionary.get("source_metadata") if isinstance(dictionary, Mapping) else None
    loaded_version = None
    if isinstance(source_metadata, Mapping):
        loaded_version = _normalized_string(source_metadata.get("dictionary_version"))
    if current_resolution is not None and supplied_candidate is not None:
        for candidate in current_resolution["candidates"]:
            expected_candidate = _candidate_audit_view(candidate)
            if supplied_candidate == expected_candidate:
                matched_candidate = expected_candidate
                break
        if (
            matched_candidate is None
            and current_resolution["resolution_status"] == "unresolved"
        ):
            if (
                not _semantically_complete_input(original_input, normalized_input)
                or current_resolution["resolution_reasons"]
                != ["no_deterministic_semantic_match"]
            ):
                candidate_errors = ["human_selected_semantic_input_incomplete"]
            else:
                matched_candidate, candidate_errors = _human_selected_candidate(
                    supplied_candidate,
                    selected_class_id=selected_class_id,
                    classes=classes,
                    dictionary_version=loaded_version,
                )

    errors = []
    if actor_id is None:
        errors.append("actor_id_missing")
    if confirmed_at is None:
        errors.append("confirmed_at_missing")
    else:
        parsed_confirmation_time = _parse_confirmation_time(confirmed_at)
        if parsed_confirmation_time is None:
            errors.append("confirmed_at_invalid")
        elif (
            parsed_confirmation_time.tzinfo is None
            or parsed_confirmation_time.utcoffset() is None
        ):
            errors.append("confirmed_at_timezone_missing")
    if selected_class_id is None:
        errors.append("selected_standard_class_id_missing")
    if normalized_input is None:
        errors.append("current_original_input_missing")
    if supplied_candidate is None:
        errors.append("selected_candidate_evidence_missing")
    elif matched_candidate is None:
        errors.extend(candidate_errors or ["selected_candidate_evidence_mismatch"])
    elif (
        matched_candidate["standard_class_id"] is not None
        and selected_class_id is not None
        and matched_candidate["standard_class_id"] != selected_class_id
    ):
        errors.append("selected_candidate_class_mismatch")
    if supplied_input_digest is None:
        errors.append("original_input_digest_missing")
    elif expected_input_digest is not None and supplied_input_digest != expected_input_digest:
        errors.append("original_input_digest_mismatch")
    if supplied_dictionary_version is None:
        errors.append("dictionary_version_missing")

    dictionary_ready = isinstance(dictionary, Mapping) and dictionary.get("ready") is True
    if not dictionary_ready:
        errors.append("authoritative_dictionary_not_ready")
    if selected_class_id is not None and selected_class_id not in classes:
        if "selected_standard_class_not_in_dictionary" not in errors:
            errors.append("selected_standard_class_not_in_dictionary")
    if (
        supplied_dictionary_version is not None
        and supplied_dictionary_version != loaded_version
    ):
        errors.append("dictionary_version_mismatch")

    return {
        "schema": CONFIRMATION_SCHEMA,
        "valid": not errors,
        "scope": "single_request",
        "actor_id": actor_id,
        "confirmed_at": confirmed_at,
        "selected_standard_class_id": selected_class_id,
        "original_input_digest": supplied_input_digest,
        "original_input": _raw_input_audit_view(original_input),
        "normalized_input": normalized_input,
        "selected_candidate": matched_candidate,
        "selected_candidate_evidence": (
            matched_candidate["evidence"] if matched_candidate is not None else None
        ),
        "dictionary_version": supplied_dictionary_version,
        "dictionary_content_digest": (
            _normalized_string(dictionary.get("content_digest"))
            if isinstance(dictionary, Mapping)
            else None
        ),
        "mutates_authoritative_dictionary": False,
        "validation_errors": errors,
    }
