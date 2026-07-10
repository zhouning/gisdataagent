from __future__ import annotations

from copy import deepcopy

import pytest

from data_agent.uwm.traditional_livability_facility_dictionary import (
    DICTIONARY_SCHEMA,
    compute_canonical_content_digest,
    unavailable_facility_dictionary,
    validate_facility_dictionary,
)
from data_agent.uwm.traditional_livability_s6_semantics import (
    resolve_s6_facility_semantics,
    validate_human_confirmation,
)


def authoritative_dictionary_fixture(
    *,
    alias: str = "传统市集",
    class_id: str = "facility.market",
) -> dict:
    classes = [
        {
            "class_id": class_id,
            "label": "传统市场",
            "fp_fpp_references": [],
        }
    ]
    classes.extend(
        {
            "class_id": f"facility.fixture.{index:02d}",
            "label": f"Fixture facility {index:02d}",
            "fp_fpp_references": [],
        }
        for index in range(2, 44)
    )
    payload = {
        "schema": DICTIONARY_SCHEMA,
        "dictionary_version": "liv-2.0-fixture-v1",
        "issuing_organization": "Fixture standards authority",
        "source_reference": "fixture://liv-2.0/dictionary",
        "version_date": "2026-07-10",
        "authoritative_complete_43_class_dictionary": True,
        "classes": classes,
        "aliases": [
            {
                "alias": alias,
                "class_id": class_id,
                "source_reference": "fixture://liv-2.0/dictionary#market-alias",
            }
        ],
        "keywords": [
            {
                "keyword": "室内市场",
                "class_id": class_id,
                "source_reference": "fixture://liv-2.0/dictionary#market-keyword",
            }
        ],
        "imported_at": "2026-07-10T08:00:00Z",
    }
    payload["content_digest"] = compute_canonical_content_digest(payload)
    result = validate_facility_dictionary(payload)
    assert result["ready"] is True
    return result


def test_exact_authoritative_alias_can_confirm_class():
    result = resolve_s6_facility_semantics(
        facility_name="社区传统市集",
        raw_facility_type="  传统市集  ",
        use_description="固定室内市场",
        dictionary=authoritative_dictionary_fixture(alias="传统市集"),
    )

    assert result["resolution_status"] == "authoritative_confirmed"
    assert result["confirmed_standard_class_id"] == "facility.market"
    assert result["candidates"][0]["match_method"] == "authoritative_alias_exact"
    assert result["candidates"][0]["confidence"] == "exact"
    assert result["candidates"][0]["evidence"][0]["input_field"] == "raw_facility_type"


def test_controlled_keyword_can_confirm_only_one_authoritative_class():
    result = resolve_s6_facility_semantics(
        facility_name="社区服务设施",
        raw_facility_type="其他",
        use_description="提供固定室内市场服务",
        dictionary=authoritative_dictionary_fixture(),
    )

    assert result["resolution_status"] == "authoritative_confirmed"
    assert result["confirmed_standard_class_id"] == "facility.market"
    assert result["candidates"][0]["match_method"] == "authoritative_keyword_controlled"
    assert result["candidates"][0]["confidence"] == "controlled_rule"


def test_conflicting_authoritative_aliases_fail_closed():
    dictionary = authoritative_dictionary_fixture()
    conflicting = deepcopy(dictionary)
    conflicting["classes"][1]["class_id"] = "facility.hall"
    conflicting["classes"][1]["label"] = "社区礼堂"
    conflicting["aliases"].append(
        {
            "alias": "社区礼堂",
            "class_id": "facility.hall",
            "source_reference": "fixture://liv-2.0/dictionary#hall-alias",
        }
    )
    conflicting["alias_index"]["社区礼堂"] = "facility.hall"

    result = resolve_s6_facility_semantics(
        facility_name="社区礼堂",
        raw_facility_type="传统市集",
        use_description="",
        dictionary=conflicting,
    )

    assert result["resolution_status"] == "unresolved"
    assert result["confirmed_standard_class_id"] is None
    assert [row["standard_class_id"] for row in result["candidates"]] == [
        "facility.hall",
        "facility.market",
    ]
    assert result["resolution_reasons"] == ["ambiguous_authoritative_alias_matches"]


def test_internal_match_is_suggestion_only():
    result = resolve_s6_facility_semantics(
        facility_name="流动食品车",
        raw_facility_type="食品车",
        use_description="临时餐饮服务",
        dictionary=unavailable_facility_dictionary(),
    )

    assert result["resolution_status"] == "suggested_review_required"
    assert result["candidates"][0]["authority_level"] == "internal_suggestion"
    assert result["candidates"][0]["confidence"] == "weak_suggestion"
    assert result["confirmed_standard_class_id"] is None
    assert result["candidates"][0]["standard_class_id"] is None


def test_internal_match_stays_suggested_with_ready_dictionary():
    result = resolve_s6_facility_semantics(
        facility_name="流动食品车",
        raw_facility_type="食品车",
        use_description="临时餐饮服务",
        dictionary=authoritative_dictionary_fixture(),
    )

    assert result["resolution_status"] == "suggested_review_required"
    assert result["confirmed_standard_class_id"] is None
    assert result["candidates"][0]["authority_level"] == "internal_suggestion"


def test_original_input_digest_binds_the_raw_request_text():
    dictionary = unavailable_facility_dictionary()

    first = resolve_s6_facility_semantics(
        facility_name="社区传统市集",
        raw_facility_type="传统市集",
        use_description="固定室内市场",
        dictionary=dictionary,
    )
    second = resolve_s6_facility_semantics(
        facility_name="社区传统市集",
        raw_facility_type=" 传统市集 ",
        use_description="固定室内市场",
        dictionary=dictionary,
    )

    assert first["original_input_digest"] != second["original_input_digest"]


@pytest.mark.parametrize(
    ("facility_name", "raw_facility_type", "use_description"),
    [
        (None, None, None),
        ("", "  ", ""),
        (123, [], {}),
        ("未知设施", "其他", "用途不详"),
    ],
)
def test_unknown_or_incomplete_input_returns_unresolved(
    facility_name,
    raw_facility_type,
    use_description,
):
    result = resolve_s6_facility_semantics(
        facility_name=facility_name,
        raw_facility_type=raw_facility_type,
        use_description=use_description,
        dictionary=unavailable_facility_dictionary(),
    )

    assert result["resolution_status"] == "unresolved"
    assert result["confirmed_standard_class_id"] is None
    assert result["candidates"] == []


def test_malformed_non_json_input_fails_closed_without_crashing():
    result = resolve_s6_facility_semantics(
        facility_name=object(),
        raw_facility_type=None,
        use_description=None,
        dictionary=unavailable_facility_dictionary(),
    )

    assert result["resolution_status"] == "unresolved"
    assert result["resolution_reasons"] == ["facility_semantic_input_missing"]
    assert result["original_input_digest"].startswith("sha256:")


def test_human_confirmation_is_request_scoped_and_auditable():
    confirmation = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": "sha256:fixture",
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=authoritative_dictionary_fixture(class_id="facility.market"),
        original_input_digest="sha256:fixture",
    )

    assert confirmation["valid"] is True
    assert confirmation["mutates_authoritative_dictionary"] is False
    assert confirmation["scope"] == "single_request"
    assert confirmation["validation_errors"] == []


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("actor_id", "", "actor_id_missing"),
        ("confirmed_at", "2026-07-10", "confirmed_at_timezone_missing"),
        ("confirmed_at", "not-a-timestamp", "confirmed_at_invalid"),
        ("selected_standard_class_id", "facility.unknown", "selected_standard_class_not_in_dictionary"),
        ("original_input_digest", "", "original_input_digest_missing"),
        ("dictionary_version", "liv-2.0-stale", "dictionary_version_mismatch"),
    ],
)
def test_human_confirmation_rejects_incomplete_or_stale_scope(field, value, expected_error):
    payload = {
        "actor_id": "reviewer-001",
        "confirmed_at": "2026-07-10T08:00:00Z",
        "selected_standard_class_id": "facility.market",
        "original_input_digest": "sha256:fixture",
        "dictionary_version": "liv-2.0-fixture-v1",
    }
    payload[field] = value

    result = validate_human_confirmation(
        payload,
        dictionary=authoritative_dictionary_fixture(),
        original_input_digest="sha256:fixture",
    )

    assert result["valid"] is False
    assert expected_error in result["validation_errors"]
    assert result["mutates_authoritative_dictionary"] is False


def test_human_confirmation_rejects_another_requests_input_digest():
    result = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": "sha256:another-request",
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=authoritative_dictionary_fixture(),
        original_input_digest="sha256:fixture",
    )

    assert result["valid"] is False
    assert result["validation_errors"] == ["original_input_digest_mismatch"]
