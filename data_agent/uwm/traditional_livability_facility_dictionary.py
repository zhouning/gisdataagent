from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


DICTIONARY_SCHEMA = "uwm.traditional_livability.facility_dictionary.v1"
COMPATIBILITY_SCHEMA = "uwm.traditional_livability.facility_compatibility.v1"
ALLOWED_RELATIONSHIPS = {"conflict", "compatible"}

_DICTIONARY_MISSING_BLOCKER = "authoritative_43_class_facility_dictionary_missing"
_DICTIONARY_INCOMPLETE_BLOCKER = "authoritative_43_class_facility_dictionary_incomplete"
_ALIAS_PROVENANCE_BLOCKER = "authoritative_alias_keyword_provenance_missing"
_COMPATIBILITY_MISSING_BLOCKER = "authoritative_facility_compatibility_matrix_missing"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _source_metadata(payload: Mapping[str, Any], *, version_field: str) -> dict[str, Any]:
    return {
        version_field: payload.get(version_field),
        "issuing_organization": payload.get("issuing_organization"),
        "source_reference": payload.get("source_reference"),
        "effective_date": payload.get("effective_date") or payload.get("version_date"),
        "version_date": payload.get("version_date"),
        "imported_at": payload.get("imported_at"),
    }


def _validate_source_metadata(
    payload: Mapping[str, Any],
    *,
    version_field: str,
    error_prefix: str,
) -> list[str]:
    errors = []
    required_fields = {
        version_field: f"{error_prefix}_version_missing",
        "issuing_organization": f"{error_prefix}_issuing_organization_missing",
        "source_reference": f"{error_prefix}_source_reference_missing",
        "content_digest": f"{error_prefix}_content_digest_missing",
        "imported_at": f"{error_prefix}_import_timestamp_missing",
    }
    for field, error in required_fields.items():
        if not _text(payload.get(field)):
            errors.append(error)
    if not _text(payload.get("effective_date") or payload.get("version_date")):
        errors.append(f"{error_prefix}_effective_or_version_date_missing")
    return errors


def validate_facility_dictionary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the normalized dictionary, validation errors and blockers."""
    if not isinstance(payload, Mapping):
        payload = {}

    errors = []
    if payload.get("schema") != DICTIONARY_SCHEMA:
        errors.append("dictionary_schema_invalid")
    errors.extend(
        _validate_source_metadata(
            payload,
            version_field="dictionary_version",
            error_prefix="dictionary",
        )
    )

    raw_classes = payload.get("classes")
    classes = deepcopy(raw_classes) if isinstance(raw_classes, list) else []
    if not isinstance(raw_classes, list) or not raw_classes:
        errors.append("facility_classes_missing")

    class_ids = set()
    for index, facility_class in enumerate(classes):
        if not isinstance(facility_class, Mapping):
            errors.append(f"facility_class_invalid:{index}")
            continue
        class_id = _text(facility_class.get("class_id"))
        if not class_id:
            errors.append(f"facility_class_id_missing:{index}")
        elif class_id in class_ids:
            errors.append(f"duplicate_facility_class_id:{class_id}")
        else:
            class_ids.add(class_id)
        if not _text(facility_class.get("label")):
            errors.append(f"facility_class_label_missing:{class_id or index}")

    class_count = len(classes)
    completeness_claim = payload.get("authoritative_complete_43_class_dictionary") is True
    if completeness_claim and class_count != 43:
        errors.append("authoritative_complete_dictionary_requires_43_classes")
    elif not completeness_claim:
        errors.append("authoritative_complete_dictionary_not_declared")

    aliases = deepcopy(payload.get("aliases")) if isinstance(payload.get("aliases"), list) else []
    alias_index: dict[str, str] = {}
    provenance_missing = False
    for index, alias_entry in enumerate(aliases):
        if not isinstance(alias_entry, Mapping):
            errors.append(f"alias_entry_invalid:{index}")
            continue
        alias = _text(alias_entry.get("alias"))
        class_id = _text(alias_entry.get("class_id"))
        if not alias:
            errors.append(f"alias_value_missing:{index}")
            continue
        if class_id not in class_ids:
            errors.append(f"alias_references_unknown_class:{alias}")
        if alias in alias_index and alias_index[alias] != class_id:
            errors.append(f"duplicate_alias_with_conflicting_class:{alias}")
        else:
            alias_index[alias] = class_id
        if not _text(alias_entry.get("source_reference")):
            provenance_missing = True
            errors.append(f"alias_provenance_missing:{alias}")

    keywords = deepcopy(payload.get("keywords")) if isinstance(payload.get("keywords"), list) else []
    keyword_index: dict[str, list[str]] = {}
    for index, keyword_entry in enumerate(keywords):
        if not isinstance(keyword_entry, Mapping):
            errors.append(f"keyword_entry_invalid:{index}")
            continue
        keyword = _text(keyword_entry.get("keyword"))
        class_id = _text(keyword_entry.get("class_id"))
        if not keyword:
            errors.append(f"keyword_value_missing:{index}")
            continue
        if class_id not in class_ids:
            errors.append(f"keyword_references_unknown_class:{keyword}")
        indexed_classes = keyword_index.setdefault(keyword, [])
        if class_id not in indexed_classes:
            indexed_classes.append(class_id)
        if not _text(keyword_entry.get("source_reference")):
            provenance_missing = True
            errors.append(f"keyword_provenance_missing:{keyword}")

    authoritative_complete = completeness_claim and class_count == 43 and not errors
    blockers = []
    if not authoritative_complete:
        blockers.append(_DICTIONARY_INCOMPLETE_BLOCKER)
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
        "source_metadata": _source_metadata(payload, version_field="dictionary_version"),
        "content_digest": payload.get("content_digest"),
        "validation_errors": errors,
        "production_blockers": blockers,
    }


def unavailable_facility_dictionary() -> dict[str, Any]:
    """Return the explicit no-authoritative-dictionary contract."""
    return {
        "schema": DICTIONARY_SCHEMA,
        "ready": False,
        "status": "dictionary_unavailable",
        "authoritative_complete_43_class_dictionary": False,
        "class_count": 0,
        "classes": [],
        "aliases": [],
        "keywords": [],
        "alias_index": {},
        "keyword_index": {},
        "source_metadata": _source_metadata({}, version_field="dictionary_version"),
        "content_digest": None,
        "validation_errors": [],
        "production_blockers": [_DICTIONARY_MISSING_BLOCKER],
    }


def validate_compatibility_matrix(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return normalized authoritative compatibility rules."""
    if not isinstance(payload, Mapping):
        payload = {}

    errors = []
    if payload.get("schema") != COMPATIBILITY_SCHEMA:
        errors.append("compatibility_matrix_schema_invalid")
    errors.extend(
        _validate_source_metadata(
            payload,
            version_field="matrix_version",
            error_prefix="compatibility_matrix",
        )
    )

    raw_rules = payload.get("rules")
    rules = deepcopy(raw_rules) if isinstance(raw_rules, list) else []
    if not isinstance(raw_rules, list) or not raw_rules:
        errors.append("compatibility_rules_missing")

    rule_index: dict[str, dict[str, Any]] = {}
    for index, rule in enumerate(rules):
        if not isinstance(rule, Mapping):
            errors.append(f"compatibility_rule_invalid:{index}")
            continue
        rule_id = _text(rule.get("rule_id"))
        relationship = _text(rule.get("relationship"))
        if not rule_id:
            errors.append("compatibility_rule_id_missing")
        elif rule_id in rule_index:
            errors.append(f"duplicate_compatibility_rule_id:{rule_id}")
        else:
            rule_index[rule_id] = rule
        if relationship not in ALLOWED_RELATIONSHIPS:
            errors.append(f"unsupported_compatibility_relationship:{relationship}")
        if not _text(rule.get("subject_class_id")):
            errors.append(f"compatibility_subject_class_id_missing:{rule_id or index}")
        if not _text(rule.get("object_class_id")):
            errors.append(f"compatibility_object_class_id_missing:{rule_id or index}")
        if not _text(rule.get("source_reference")):
            errors.append(f"compatibility_rule_provenance_missing:{rule_id or index}")

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
        "source_metadata": _source_metadata(payload, version_field="matrix_version"),
        "content_digest": payload.get("content_digest"),
        "validation_errors": errors,
        "production_blockers": [] if ready else [_COMPATIBILITY_MISSING_BLOCKER],
    }


def unavailable_compatibility_matrix() -> dict[str, Any]:
    """Return the explicit no-authoritative-rule contract."""
    return {
        "schema": COMPATIBILITY_SCHEMA,
        "ready": False,
        "status": "compatibility_matrix_unavailable",
        "rules": [],
        "rule_index": {},
        "source_metadata": _source_metadata({}, version_field="matrix_version"),
        "content_digest": None,
        "validation_errors": [],
        "production_blockers": [_COMPATIBILITY_MISSING_BLOCKER],
    }
