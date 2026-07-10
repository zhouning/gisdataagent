from __future__ import annotations

from copy import deepcopy

from data_agent.uwm.traditional_livability_facility_dictionary import (
    COMPATIBILITY_SCHEMA,
    DICTIONARY_SCHEMA,
    compute_canonical_content_digest,
    unavailable_compatibility_matrix,
    unavailable_facility_dictionary,
    validate_compatibility_matrix,
    validate_facility_dictionary,
)


def dictionary_fixture(*, class_count: int = 43) -> dict:
    payload = {
        "schema": DICTIONARY_SCHEMA,
        "dictionary_version": "fixture-dictionary-2026-07-10",
        "issuing_organization": "Fixture standards authority",
        "source_reference": "fixture://liv-2.0/dictionary",
        "version_date": "2026-07-10",
        "authoritative_complete_43_class_dictionary": True,
        "classes": [
            {
                "class_id": f"fixture.class.{index:02d}",
                "label": f"Fixture class {index:02d}",
                "fp_fpp_references": [],
            }
            for index in range(1, class_count + 1)
        ],
        "aliases": [
            {
                "alias": "fixture alias",
                "class_id": "fixture.class.01",
                "source_reference": "fixture://liv-2.0/dictionary#alias-1",
            }
        ],
        "keywords": [
            {
                "keyword": "fixture keyword",
                "class_id": "fixture.class.02",
                "source_reference": "fixture://liv-2.0/dictionary#keyword-1",
            }
        ],
        "imported_at": "2026-07-10T00:00:00Z",
    }
    payload["content_digest"] = compute_canonical_content_digest(payload)
    return payload


def matrix_fixture(*, rule_id: str = "fixture-rule-001") -> dict:
    payload = {
        "schema": COMPATIBILITY_SCHEMA,
        "matrix_version": "fixture-matrix-2026-07-10",
        "issuing_organization": "Fixture standards authority",
        "source_reference": "fixture://liv-2.0/compatibility",
        "version_date": "2026-07-10",
        "rules": [
            {
                "rule_id": rule_id,
                "rule_version": "fixture-rule-version-1",
                "subject_class_id": "fixture.class.01",
                "object_class_id": "fixture.class.02",
                "relationship": "conflict",
                "applicability_conditions": {
                    "planning_area_types": ["fixture_planning_area"]
                },
                "source_reference": "fixture://liv-2.0/compatibility#rule-1",
            }
        ],
        "imported_at": "2026-07-10T00:00:00Z",
    }
    payload["content_digest"] = compute_canonical_content_digest(payload)
    return payload


def test_load_dictionary_preserves_authority_and_exact_class_count():
    payload = dictionary_fixture(class_count=43)

    result = validate_facility_dictionary(payload)

    assert result["ready"] is True
    assert result["authoritative_complete_43_class_dictionary"] is True
    assert result["class_count"] == 43
    assert result["production_blockers"] == []
    assert result["classes"] == payload["classes"]
    assert result["alias_index"] == {"fixture alias": "fixture.class.01"}
    assert result["keyword_index"] == {"fixture keyword": ["fixture.class.02"]}
    assert result["source_metadata"]["dictionary_version"] == payload["dictionary_version"]
    assert result["content_digest"] == payload["content_digest"]


def test_missing_dictionary_never_promotes_internal_taxonomy():
    result = unavailable_facility_dictionary()

    assert result["ready"] is False
    assert result["status"] == "dictionary_unavailable"
    assert result["classes"] == []
    assert result["alias_index"] == {}
    assert result["keyword_index"] == {}
    assert "authoritative_43_class_facility_dictionary_missing" in result["production_blockers"]


def test_compatibility_rule_requires_provenance_and_stable_rule_id():
    payload = matrix_fixture(rule_id="")
    payload["content_digest"] = compute_canonical_content_digest(payload)

    result = validate_compatibility_matrix(payload)

    assert result["ready"] is False
    assert "compatibility_rule_id_missing" in result["validation_errors"]


def test_dictionary_rejects_duplicate_class_ids():
    payload = dictionary_fixture()
    payload["classes"][1]["class_id"] = payload["classes"][0]["class_id"]
    payload["content_digest"] = compute_canonical_content_digest(payload)

    result = validate_facility_dictionary(payload)

    assert result["ready"] is False
    assert "duplicate_facility_class_id:fixture.class.01" in result["validation_errors"]


def test_dictionary_rejects_aliases_pointing_to_unknown_classes():
    payload = dictionary_fixture()
    payload["aliases"][0]["class_id"] = "fixture.class.unknown"
    payload["content_digest"] = compute_canonical_content_digest(payload)

    result = validate_facility_dictionary(payload)

    assert result["ready"] is False
    assert "alias_references_unknown_class:fixture alias" in result["validation_errors"]


def test_compatibility_matrix_rejects_unsupported_relationship_values():
    payload = matrix_fixture()
    payload["rules"][0]["relationship"] = "possibly_conflicting"
    payload["content_digest"] = compute_canonical_content_digest(payload)

    result = validate_compatibility_matrix(payload)

    assert result["ready"] is False
    assert "unsupported_compatibility_relationship:possibly_conflicting" in result["validation_errors"]


def test_dictionary_rejects_completeness_claim_with_non_43_count():
    payload = dictionary_fixture(class_count=42)

    result = validate_facility_dictionary(payload)

    assert result["ready"] is False
    assert result["authoritative_complete_43_class_dictionary"] is False
    assert result["status"] == "dictionary_incomplete"
    assert "authoritative_complete_dictionary_requires_43_classes" in result["validation_errors"]
    assert "authoritative_43_class_facility_dictionary_incomplete" in result["production_blockers"]


def test_dictionary_does_not_mutate_the_imported_payload():
    payload = dictionary_fixture()
    original = deepcopy(payload)

    validate_facility_dictionary(payload)

    assert payload == original


def test_compatibility_matrix_preserves_normalized_rules_and_source_metadata():
    payload = matrix_fixture()

    result = validate_compatibility_matrix(payload)

    assert result["ready"] is True
    assert result["status"] == "ready"
    assert result["rules"] == payload["rules"]
    assert result["rule_index"] == {"fixture-rule-001": payload["rules"][0]}
    assert result["source_metadata"]["matrix_version"] == payload["matrix_version"]
    assert result["production_blockers"] == []


def test_compatibility_rule_requires_rule_level_provenance():
    payload = matrix_fixture()
    payload["rules"][0]["source_reference"] = ""
    payload["content_digest"] = compute_canonical_content_digest(payload)

    result = validate_compatibility_matrix(payload)

    assert result["ready"] is False
    assert "compatibility_rule_provenance_missing:fixture-rule-001" in result["validation_errors"]


def test_missing_compatibility_matrix_is_explicitly_unavailable():
    result = unavailable_compatibility_matrix()

    assert result["ready"] is False
    assert result["status"] == "compatibility_matrix_unavailable"
    assert result["rules"] == []
    assert result["rule_index"] == {}
    assert result["content_digest"] is None
    assert result["validation_errors"] == []
    assert "authoritative_facility_compatibility_matrix_missing" in result["production_blockers"]


def test_compatibility_rule_requires_non_empty_rule_version():
    payload = matrix_fixture()
    payload["rules"][0]["rule_version"] = ""
    payload["content_digest"] = compute_canonical_content_digest(payload)

    result = validate_compatibility_matrix(payload)

    assert result["ready"] is False
    assert "compatibility_rule_version_missing:fixture-rule-001" in result["validation_errors"]


def test_compatibility_rule_requires_explicit_applicability_conditions():
    payload = matrix_fixture()
    payload["rules"][0].pop("applicability_conditions")
    payload["content_digest"] = compute_canonical_content_digest(payload)

    result = validate_compatibility_matrix(payload)

    assert result["ready"] is False
    assert (
        "compatibility_rule_applicability_conditions_missing:fixture-rule-001"
        in result["validation_errors"]
    )


def test_dictionary_digest_covers_entire_canonical_payload_except_digest_field():
    payload = dictionary_fixture()
    original_digest = payload["content_digest"]
    reordered_payload = dict(reversed(list(payload.items())))

    assert compute_canonical_content_digest(reordered_payload) == original_digest

    payload["classes"][0]["label"] = "Changed fixture class"
    result = validate_facility_dictionary(payload)

    assert result["ready"] is False
    assert result["content_digest"] != original_digest
    assert result["provided_content_digest"] == original_digest
    assert "dictionary_content_digest_mismatch" in result["validation_errors"]
    assert result["digest_contract"]["excluded_top_level_fields"] == ["content_digest"]


def test_compatibility_digest_mismatch_fails_readiness():
    payload = matrix_fixture()
    original_digest = payload["content_digest"]
    payload["rules"][0]["applicability_conditions"] = ["changed-condition"]

    result = validate_compatibility_matrix(payload)

    assert result["ready"] is False
    assert result["content_digest"] != original_digest
    assert result["provided_content_digest"] == original_digest
    assert "compatibility_matrix_content_digest_mismatch" in result["validation_errors"]


def test_provided_digest_requires_an_exact_untrimmed_match():
    payload = dictionary_fixture()
    payload["content_digest"] = f" {payload['content_digest']} "

    result = validate_facility_dictionary(payload)

    assert result["ready"] is False
    assert "dictionary_content_digest_mismatch" in result["validation_errors"]


def test_compatibility_validation_does_not_mutate_the_imported_payload():
    payload = matrix_fixture()
    original = deepcopy(payload)

    validate_compatibility_matrix(payload)

    assert payload == original
