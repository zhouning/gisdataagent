from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from typing import Any, Mapping


DICTIONARY_SCHEMA = "uwm.traditional_livability.facility_dictionary.v1"
COMPATIBILITY_SCHEMA = "uwm.traditional_livability.facility_compatibility.v1"
ALLOWED_RELATIONSHIPS = {"conflict", "compatible"}

_DICTIONARY_MISSING_BLOCKER = "authoritative_43_class_facility_dictionary_missing"
_DICTIONARY_INCOMPLETE_BLOCKER = "authoritative_43_class_facility_dictionary_incomplete"
_ALIAS_PROVENANCE_BLOCKER = "authoritative_alias_keyword_provenance_missing"
_COMPATIBILITY_MISSING_BLOCKER = "authoritative_facility_compatibility_matrix_missing"
_COMPATIBILITY_INCOMPLETE_BLOCKER = "authoritative_facility_compatibility_matrix_incomplete"
_COMPATIBILITY_MALFORMED_BLOCKER = "authoritative_facility_compatibility_matrix_malformed"

_DIGEST_CONTRACT = {
    "algorithm": "sha256",
    "encoding": "utf-8",
    "serialization": "canonical_json_sorted_keys_compact_separators_preserve_list_order",
    "covered_fields": "all_top_level_source_payload_fields_and_nested_values",
    "excluded_top_level_fields": ["content_digest"],
}


def _normalized_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _canonical_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical payload object keys must be strings")
        return {key: _canonical_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical_json_value(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"unsupported canonical payload value: {type(value).__name__}")


def compute_canonical_content_digest(payload: Mapping[str, Any]) -> str:
    """Hash all canonical source fields except top-level ``content_digest``."""
    digest_payload = {
        key: value
        for key, value in payload.items()
        if key not in _DIGEST_CONTRACT["excluded_top_level_fields"]
    }
    serialized = json.dumps(
        _canonical_json_value(digest_payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{sha256(serialized).hexdigest()}"


def _payload_has_schema(payload: Any, expected_schema: str) -> bool:
    if not isinstance(payload, Mapping):
        return False
    try:
        return payload.get("schema") == expected_schema
    except Exception:
        return False


def _empty_source_metadata(version_field: str) -> dict[str, Any]:
    return {
        version_field: None,
        "issuing_organization": None,
        "source_reference": None,
        "effective_date": None,
        "version_date": None,
        "imported_at": None,
    }


def _invalid_dictionary_content_contract(payload: Any) -> dict[str, Any]:
    status = (
        "dictionary_incomplete"
        if _payload_has_schema(payload, DICTIONARY_SCHEMA)
        else "dictionary_schema_invalid"
    )
    return {
        "schema": DICTIONARY_SCHEMA,
        "ready": False,
        "status": status,
        "authoritative_complete_43_class_dictionary": False,
        "class_count": 0,
        "classes": [],
        "aliases": [],
        "keywords": [],
        "alias_index": {},
        "keyword_index": {},
        "source_metadata": _empty_source_metadata("dictionary_version"),
        "content_digest": None,
        "provided_content_digest": None,
        "digest_contract": deepcopy(_DIGEST_CONTRACT),
        "validation_errors": ["content_not_canonical_json"],
        "production_blockers": [_DICTIONARY_INCOMPLETE_BLOCKER],
    }


def _invalid_compatibility_content_contract(payload: Any) -> dict[str, Any]:
    status = (
        "compatibility_matrix_incomplete"
        if _payload_has_schema(payload, COMPATIBILITY_SCHEMA)
        else "compatibility_matrix_schema_invalid"
    )
    return {
        "schema": COMPATIBILITY_SCHEMA,
        "ready": False,
        "status": status,
        "rules": [],
        "rule_index": {},
        "source_metadata": _empty_source_metadata("matrix_version"),
        "content_digest": None,
        "provided_content_digest": None,
        "digest_contract": deepcopy(_DIGEST_CONTRACT),
        "validation_errors": ["content_not_canonical_json"],
        "production_blockers": [_COMPATIBILITY_MALFORMED_BLOCKER],
    }


def _normalize_required_string(
    value: Any,
    *,
    missing_error: str,
    not_string_error: str,
    errors: list[str],
) -> str | None:
    if not isinstance(value, str):
        errors.append(not_string_error)
        return None
    normalized = value.strip()
    if not normalized:
        errors.append(missing_error)
        return None
    return normalized


def _normalize_source_metadata(
    payload: Mapping[str, Any],
    *,
    version_field: str,
    error_prefix: str,
    errors: list[str],
) -> dict[str, Any]:
    version = _normalize_required_string(
        payload.get(version_field),
        missing_error=f"{error_prefix}_version_missing",
        not_string_error=f"{error_prefix}_version_not_string",
        errors=errors,
    )
    issuing_organization = _normalize_required_string(
        payload.get("issuing_organization"),
        missing_error=f"{error_prefix}_issuing_organization_missing",
        not_string_error=f"{error_prefix}_issuing_organization_not_string",
        errors=errors,
    )
    source_reference = _normalize_required_string(
        payload.get("source_reference"),
        missing_error=f"{error_prefix}_source_reference_missing",
        not_string_error=f"{error_prefix}_source_reference_not_string",
        errors=errors,
    )
    imported_at = _normalize_required_string(
        payload.get("imported_at"),
        missing_error=f"{error_prefix}_import_timestamp_missing",
        not_string_error=f"{error_prefix}_import_timestamp_not_string",
        errors=errors,
    )
    version_date = _normalized_string(payload.get("version_date"))
    effective_date_value = payload.get("effective_date")
    effective_date_is_blank = isinstance(effective_date_value, str) and not effective_date_value.strip()
    selected_date = (
        payload.get("version_date")
        if effective_date_value is None or effective_date_is_blank
        else effective_date_value
    )
    effective_date = _normalize_required_string(
        selected_date,
        missing_error=f"{error_prefix}_effective_or_version_date_missing",
        not_string_error=f"{error_prefix}_effective_or_version_date_not_string",
        errors=errors,
    )
    return {
        version_field: version,
        "issuing_organization": issuing_organization,
        "source_reference": source_reference,
        "effective_date": effective_date,
        "version_date": version_date,
        "imported_at": imported_at,
    }


def _normalize_content_digest(
    payload: Mapping[str, Any],
    *,
    error_prefix: str,
    computed_digest: str,
    errors: list[str],
) -> str | None:
    provided = payload.get("content_digest")
    if not isinstance(provided, str):
        errors.append(f"{error_prefix}_content_digest_not_string")
        return None
    if not provided.strip():
        errors.append(f"{error_prefix}_content_digest_missing")
        return None
    if provided != computed_digest:
        errors.append(f"{error_prefix}_content_digest_mismatch")
    return provided


def _normalize_dictionary_records(
    payload: Mapping[str, Any],
    errors: list[str],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, str],
    dict[str, list[str]],
    bool,
]:
    raw_classes = payload.get("classes")
    if not isinstance(raw_classes, list) or not raw_classes:
        errors.append("facility_classes_missing")
        raw_classes = []

    classes = []
    class_ids = set()
    for index, raw_class in enumerate(raw_classes):
        if not isinstance(raw_class, Mapping):
            errors.append(f"facility_class_invalid:{index}")
            continue
        normalized_class = deepcopy(dict(raw_class))
        class_id = _normalize_required_string(
            raw_class.get("class_id"),
            missing_error=f"facility_class_id_missing:{index}",
            not_string_error=f"facility_class_id_not_string:{index}",
            errors=errors,
        )
        label_reference = class_id or index
        label = _normalize_required_string(
            raw_class.get("label"),
            missing_error=f"facility_class_label_missing:{label_reference}",
            not_string_error=f"facility_class_label_not_string:{label_reference}",
            errors=errors,
        )
        normalized_class["class_id"] = class_id
        normalized_class["label"] = label
        classes.append(normalized_class)
        if class_id is None:
            continue
        if class_id in class_ids:
            errors.append(f"duplicate_facility_class_id:{class_id}")
        else:
            class_ids.add(class_id)

    aliases = []
    alias_index: dict[str, str] = {}
    provenance_missing = False
    raw_aliases = payload.get("aliases")
    if isinstance(raw_aliases, list):
        for index, raw_alias in enumerate(raw_aliases):
            if not isinstance(raw_alias, Mapping):
                errors.append(f"alias_entry_invalid:{index}")
                continue
            normalized_alias = deepcopy(dict(raw_alias))
            alias = _normalize_required_string(
                raw_alias.get("alias"),
                missing_error=f"alias_value_missing:{index}",
                not_string_error=f"alias_value_not_string:{index}",
                errors=errors,
            )
            class_id = _normalize_required_string(
                raw_alias.get("class_id"),
                missing_error=f"alias_class_id_missing:{alias or index}",
                not_string_error=f"alias_class_id_not_string:{alias or index}",
                errors=errors,
            )
            source_reference = _normalize_required_string(
                raw_alias.get("source_reference"),
                missing_error=f"alias_provenance_missing:{alias or index}",
                not_string_error=f"alias_provenance_not_string:{alias or index}",
                errors=errors,
            )
            normalized_alias.update(
                alias=alias,
                class_id=class_id,
                source_reference=source_reference,
            )
            aliases.append(normalized_alias)
            provenance_missing = provenance_missing or source_reference is None
            if alias is None or class_id is None:
                continue
            if class_id not in class_ids:
                errors.append(f"alias_references_unknown_class:{alias}")
            elif alias in alias_index and alias_index[alias] != class_id:
                errors.append(f"duplicate_alias_with_conflicting_class:{alias}")
            else:
                alias_index[alias] = class_id

    keywords = []
    keyword_index: dict[str, list[str]] = {}
    raw_keywords = payload.get("keywords")
    if isinstance(raw_keywords, list):
        for index, raw_keyword in enumerate(raw_keywords):
            if not isinstance(raw_keyword, Mapping):
                errors.append(f"keyword_entry_invalid:{index}")
                continue
            normalized_keyword = deepcopy(dict(raw_keyword))
            keyword = _normalize_required_string(
                raw_keyword.get("keyword"),
                missing_error=f"keyword_value_missing:{index}",
                not_string_error=f"keyword_value_not_string:{index}",
                errors=errors,
            )
            class_id = _normalize_required_string(
                raw_keyword.get("class_id"),
                missing_error=f"keyword_class_id_missing:{keyword or index}",
                not_string_error=f"keyword_class_id_not_string:{keyword or index}",
                errors=errors,
            )
            source_reference = _normalize_required_string(
                raw_keyword.get("source_reference"),
                missing_error=f"keyword_provenance_missing:{keyword or index}",
                not_string_error=f"keyword_provenance_not_string:{keyword or index}",
                errors=errors,
            )
            normalized_keyword.update(
                keyword=keyword,
                class_id=class_id,
                source_reference=source_reference,
            )
            keywords.append(normalized_keyword)
            provenance_missing = provenance_missing or source_reference is None
            if keyword is None or class_id is None:
                continue
            if class_id not in class_ids:
                errors.append(f"keyword_references_unknown_class:{keyword}")
                continue
            indexed_classes = keyword_index.setdefault(keyword, [])
            if class_id not in indexed_classes:
                indexed_classes.append(class_id)

    return classes, aliases, keywords, alias_index, keyword_index, provenance_missing


def _validate_facility_dictionary(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        payload = {}
    try:
        computed_digest = compute_canonical_content_digest(payload)
    except Exception:
        return _invalid_dictionary_content_contract(payload)

    errors = []
    provided_digest = _normalize_content_digest(
        payload,
        error_prefix="dictionary",
        computed_digest=computed_digest,
        errors=errors,
    )
    if payload.get("schema") != DICTIONARY_SCHEMA:
        errors.append("dictionary_schema_invalid")
    source_metadata = _normalize_source_metadata(
        payload,
        version_field="dictionary_version",
        error_prefix="dictionary",
        errors=errors,
    )
    classes, aliases, keywords, alias_index, keyword_index, provenance_missing = (
        _normalize_dictionary_records(payload, errors)
    )

    class_count = len(classes)
    completeness_claim = payload.get("authoritative_complete_43_class_dictionary") is True
    if completeness_claim and class_count != 43:
        errors.append("authoritative_complete_dictionary_requires_43_classes")
    elif not completeness_claim:
        errors.append("authoritative_complete_dictionary_not_declared")

    authoritative_complete = completeness_claim and class_count == 43 and not errors
    blockers = [] if authoritative_complete else [_DICTIONARY_INCOMPLETE_BLOCKER]
    if provenance_missing:
        blockers.append(_ALIAS_PROVENANCE_BLOCKER)
    status = "ready"
    if errors:
        status = "dictionary_schema_invalid" if "dictionary_schema_invalid" in errors else "dictionary_incomplete"
    return {
        "schema": DICTIONARY_SCHEMA,
        "ready": authoritative_complete,
        "status": status,
        "authoritative_complete_43_class_dictionary": authoritative_complete,
        "class_count": class_count,
        "classes": classes,
        "aliases": aliases,
        "keywords": keywords,
        "alias_index": alias_index,
        "keyword_index": keyword_index,
        "source_metadata": source_metadata,
        "content_digest": computed_digest,
        "provided_content_digest": provided_digest,
        "digest_contract": deepcopy(_DIGEST_CONTRACT),
        "validation_errors": errors,
        "production_blockers": blockers,
    }


def validate_facility_dictionary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize an externally supplied authoritative dictionary."""
    try:
        return _validate_facility_dictionary(payload)
    except Exception:
        return _invalid_dictionary_content_contract(payload)


def unavailable_facility_dictionary() -> dict[str, Any]:
    """Return the explicit no-authoritative-dictionary contract."""
    result = _invalid_dictionary_content_contract({"schema": DICTIONARY_SCHEMA})
    result.update(
        status="dictionary_unavailable",
        validation_errors=[],
        production_blockers=[_DICTIONARY_MISSING_BLOCKER],
    )
    return result


def _normalize_compatibility_rules(
    payload: Mapping[str, Any],
    errors: list[str],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    raw_rules = payload.get("rules")
    if not isinstance(raw_rules, list) or not raw_rules:
        errors.append("compatibility_rules_missing")
        raw_rules = []

    rules = []
    rule_index: dict[str, dict[str, Any]] = {}
    for index, raw_rule in enumerate(raw_rules):
        if not isinstance(raw_rule, Mapping):
            errors.append(f"compatibility_rule_invalid:{index}")
            continue
        normalized_rule = deepcopy(dict(raw_rule))
        rule_id = _normalize_required_string(
            raw_rule.get("rule_id"),
            missing_error="compatibility_rule_id_missing",
            not_string_error=f"compatibility_rule_id_not_string:{index}",
            errors=errors,
        )
        reference = rule_id or index
        rule_version = _normalize_required_string(
            raw_rule.get("rule_version"),
            missing_error=f"compatibility_rule_version_missing:{reference}",
            not_string_error=f"compatibility_rule_version_not_string:{reference}",
            errors=errors,
        )
        subject_class_id = _normalize_required_string(
            raw_rule.get("subject_class_id"),
            missing_error=f"compatibility_subject_class_id_missing:{reference}",
            not_string_error=f"compatibility_subject_class_id_not_string:{reference}",
            errors=errors,
        )
        object_class_id = _normalize_required_string(
            raw_rule.get("object_class_id"),
            missing_error=f"compatibility_object_class_id_missing:{reference}",
            not_string_error=f"compatibility_object_class_id_not_string:{reference}",
            errors=errors,
        )
        relationship = _normalize_required_string(
            raw_rule.get("relationship"),
            missing_error=f"unsupported_compatibility_relationship:",
            not_string_error=f"compatibility_relationship_not_string:{reference}",
            errors=errors,
        )
        source_reference = _normalize_required_string(
            raw_rule.get("source_reference"),
            missing_error=f"compatibility_rule_provenance_missing:{reference}",
            not_string_error=f"compatibility_rule_provenance_not_string:{reference}",
            errors=errors,
        )
        normalized_rule.update(
            rule_id=rule_id,
            rule_version=rule_version,
            subject_class_id=subject_class_id,
            object_class_id=object_class_id,
            relationship=relationship,
            source_reference=source_reference,
        )
        rules.append(normalized_rule)
        if relationship is not None and relationship not in ALLOWED_RELATIONSHIPS:
            errors.append(f"unsupported_compatibility_relationship:{relationship}")
        if not isinstance(raw_rule.get("applicability_conditions"), (Mapping, list)):
            errors.append(f"compatibility_rule_applicability_conditions_missing:{reference}")
        if rule_id is None:
            continue
        if rule_id in rule_index:
            errors.append(f"duplicate_compatibility_rule_id:{rule_id}")
        else:
            rule_index[rule_id] = normalized_rule
    return rules, rule_index


def _validate_compatibility_matrix(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        payload = {}
    try:
        computed_digest = compute_canonical_content_digest(payload)
    except Exception:
        return _invalid_compatibility_content_contract(payload)

    errors = []
    provided_digest = _normalize_content_digest(
        payload,
        error_prefix="compatibility_matrix",
        computed_digest=computed_digest,
        errors=errors,
    )
    if payload.get("schema") != COMPATIBILITY_SCHEMA:
        errors.append("compatibility_matrix_schema_invalid")
    source_metadata = _normalize_source_metadata(
        payload,
        version_field="matrix_version",
        error_prefix="compatibility_matrix",
        errors=errors,
    )
    rules, rule_index = _normalize_compatibility_rules(payload, errors)
    ready = not errors
    status = "ready"
    if errors:
        status = (
            "compatibility_matrix_schema_invalid"
            if "compatibility_matrix_schema_invalid" in errors
            else "compatibility_matrix_incomplete"
        )
    return {
        "schema": COMPATIBILITY_SCHEMA,
        "ready": ready,
        "status": status,
        "rules": rules,
        "rule_index": rule_index,
        "source_metadata": source_metadata,
        "content_digest": computed_digest,
        "provided_content_digest": provided_digest,
        "digest_contract": deepcopy(_DIGEST_CONTRACT),
        "validation_errors": errors,
        "production_blockers": [] if ready else [_COMPATIBILITY_INCOMPLETE_BLOCKER],
    }


def validate_compatibility_matrix(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize externally supplied compatibility rules."""
    try:
        return _validate_compatibility_matrix(payload)
    except Exception:
        return _invalid_compatibility_content_contract(payload)


def unavailable_compatibility_matrix() -> dict[str, Any]:
    """Return the explicit no-authoritative-rule contract."""
    result = _invalid_compatibility_content_contract({"schema": COMPATIBILITY_SCHEMA})
    result.update(
        status="compatibility_matrix_unavailable",
        validation_errors=[],
        production_blockers=[_COMPATIBILITY_MISSING_BLOCKER],
    )
    return result
