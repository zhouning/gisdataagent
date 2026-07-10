from __future__ import annotations

from copy import deepcopy
import json
import math

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


def dictionary_with_secondary_class_evidence() -> dict:
    dictionary = authoritative_dictionary_fixture()
    dictionary["classes"][1]["class_id"] = "facility.hall"
    dictionary["classes"][1]["label"] = "社区礼堂"
    dictionary["aliases"].append(
        {
            "alias": "社区礼堂",
            "class_id": "facility.hall",
            "source_reference": "fixture://liv-2.0/dictionary#hall-alias",
        }
    )
    dictionary["keywords"].append(
        {
            "keyword": "礼堂",
            "class_id": "facility.hall",
            "source_reference": "fixture://liv-2.0/dictionary#hall-keyword",
        }
    )
    return dictionary


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
    assert result["candidates"][0]["dictionary_version"] == "liv-2.0-fixture-v1"
    assert result["candidates"][0]["rule_version"] is None
    assert result["candidates"][0]["human_confirmation_required"] is False
    assert result["candidates"][0]["evidence"][0]["input_field"] == "raw_facility_type"


def test_controlled_keyword_can_confirm_only_one_authoritative_class():
    result = resolve_s6_facility_semantics(
        facility_name="社区服务设施",
        raw_facility_type="  室内市场  ",
        use_description="固定服务设施",
        dictionary=authoritative_dictionary_fixture(),
    )

    assert result["resolution_status"] == "authoritative_confirmed"
    assert result["confirmed_standard_class_id"] == "facility.market"
    assert result["candidates"][0]["match_method"] == "authoritative_keyword_controlled"
    assert result["candidates"][0]["confidence"] == "controlled_rule"
    assert result["candidates"][0]["dictionary_version"] == "liv-2.0-fixture-v1"
    assert result["candidates"][0]["rule_version"] is None
    assert result["candidates"][0]["human_confirmation_required"] is False
    assert result["candidates"][0]["evidence"] == [
        {
            "input_field": "raw_facility_type",
            "matched_value": "室内市场",
            "source_reference": "fixture://liv-2.0/dictionary#market-keyword",
            "match_scope": "raw_facility_type",
            "match_mode": "exact_normalized_token",
            "negated": False,
        }
    ]


@pytest.mark.parametrize(
    ("facility_name", "use_description", "conflicting_method"),
    [
        ("社区礼堂", "固定服务设施", "authoritative_alias_exact"),
        ("社区服务设施", "拟提供礼堂配套服务", "authoritative_keyword_context_suggestion"),
    ],
    ids=["conflicting_name_alias", "conflicting_description_keyword"],
)
def test_exact_raw_keyword_does_not_confirm_against_cross_class_evidence(
    facility_name,
    use_description,
    conflicting_method,
):
    result = resolve_s6_facility_semantics(
        facility_name=facility_name,
        raw_facility_type="室内市场",
        use_description=use_description,
        dictionary=dictionary_with_secondary_class_evidence(),
    )

    assert result["resolution_status"] == "suggested_review_required"
    assert result["confirmed_standard_class_id"] is None
    assert result["resolution_reasons"] == ["conflicting_authoritative_semantic_evidence"]
    assert [candidate["standard_class_id"] for candidate in result["candidates"]] == [
        "facility.hall",
        "facility.market",
    ]
    assert all(candidate["human_confirmation_required"] is True for candidate in result["candidates"])
    assert {candidate["match_method"] for candidate in result["candidates"]} == {
        conflicting_method,
        "authoritative_keyword_controlled",
    }
    evidence_by_class = {
        candidate["standard_class_id"]: candidate["evidence"]
        for candidate in result["candidates"]
    }
    assert any(
        evidence["input_field"] == "raw_facility_type"
        and evidence["matched_value"] == "室内市场"
        for evidence in evidence_by_class["facility.market"]
    )
    expected_conflict_field = (
        "facility_name"
        if conflicting_method == "authoritative_alias_exact"
        else "use_description"
    )
    assert any(
        evidence["input_field"] == expected_conflict_field
        for evidence in evidence_by_class["facility.hall"]
    )


def test_same_class_alias_corroboration_allows_exact_raw_keyword_confirmation():
    result = resolve_s6_facility_semantics(
        facility_name="传统市集",
        raw_facility_type="室内市场",
        use_description="固定服务设施",
        dictionary=authoritative_dictionary_fixture(),
    )

    assert result["resolution_status"] == "authoritative_confirmed"
    assert result["confirmed_standard_class_id"] == "facility.market"
    assert {candidate["standard_class_id"] for candidate in result["candidates"]} == {
        "facility.market"
    }
    assert all(candidate["human_confirmation_required"] is False for candidate in result["candidates"])


@pytest.mark.parametrize(
    ("facility_name", "raw_facility_type", "use_description"),
    [
        ("室内市场配套服务点", "其他", "固定服务设施"),
        ("社区服务设施", "社区室内市场服务", "固定服务设施"),
        ("社区服务设施", "其他", "提供固定室内市场服务"),
    ],
    ids=[
        "facility_name_substring",
        "raw_facility_type_substring",
        "use_description_substring",
    ],
)
def test_keyword_substring_outside_raw_type_is_suggestion_only(
    facility_name,
    raw_facility_type,
    use_description,
):
    result = resolve_s6_facility_semantics(
        facility_name=facility_name,
        raw_facility_type=raw_facility_type,
        use_description=use_description,
        dictionary=authoritative_dictionary_fixture(),
    )

    assert result["resolution_status"] == "suggested_review_required"
    assert result["confirmed_standard_class_id"] is None
    assert result["candidates"][0]["match_method"] == "authoritative_keyword_context_suggestion"
    assert result["candidates"][0]["human_confirmation_required"] is True
    assert result["candidates"][0]["evidence"][0]["match_mode"] == "substring_context"


@pytest.mark.parametrize("negation", ["不", "非", "无", "不提供", "并非"])
def test_negated_keyword_context_never_authoritative_confirms(negation):
    result = resolve_s6_facility_semantics(
        facility_name="社区服务设施",
        raw_facility_type="室内市场",
        use_description=f"本设施{negation}室内市场服务",
        dictionary=authoritative_dictionary_fixture(),
    )

    assert result["resolution_status"] == "suggested_review_required"
    assert result["confirmed_standard_class_id"] is None
    assert all(candidate["human_confirmation_required"] is True for candidate in result["candidates"])
    assert any(
        evidence["negated"] is True
        for candidate in result["candidates"]
        for evidence in candidate["evidence"]
    )


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
    assert all(row["human_confirmation_required"] is True for row in result["candidates"])
    assert all(row["dictionary_version"] == "liv-2.0-fixture-v1" for row in result["candidates"])


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
    assert result["candidates"][0]["dictionary_version"] is None
    assert result["candidates"][0]["rule_version"] == "internal.food_truck.v1"
    assert result["candidates"][0]["human_confirmation_required"] is True
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
    assert result["candidates"][0]["dictionary_version"] == "liv-2.0-fixture-v1"
    assert result["candidates"][0]["rule_version"] == "internal.food_truck.v1"
    assert result["candidates"][0]["human_confirmation_required"] is True


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
    json.dumps(result, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize("non_finite", [math.nan, math.inf, -math.inf])
def test_non_finite_raw_input_is_json_safe_unresolved(non_finite):
    result = resolve_s6_facility_semantics(
        facility_name=non_finite,
        raw_facility_type="未分类设施",
        use_description="用途不详",
        dictionary=authoritative_dictionary_fixture(),
    )

    assert result["resolution_status"] == "unresolved"
    assert result["confirmed_standard_class_id"] is None
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_human_confirmation_is_request_scoped_and_auditable():
    original_input = {
        "facility_name": "社区传统市集",
        "raw_facility_type": " 传统市集 ",
        "use_description": "固定室内市场",
    }
    dictionary = authoritative_dictionary_fixture(class_id="facility.market")
    dictionary_before = deepcopy(dictionary)
    resolution = resolve_s6_facility_semantics(
        **original_input,
        dictionary=dictionary,
    )
    candidate = resolution["candidates"][0]
    confirmation = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=candidate,
    )

    assert confirmation["valid"] is True
    assert confirmation["mutates_authoritative_dictionary"] is False
    assert confirmation["scope"] == "single_request"
    assert confirmation["validation_errors"] == []
    assert confirmation["original_input"] == original_input
    assert confirmation["normalized_input"] == {
        "facility_name": "社区传统市集",
        "raw_facility_type": "传统市集",
        "use_description": "固定室内市场",
    }
    assert confirmation["selected_candidate_evidence"] == candidate["evidence"]
    assert confirmation["selected_candidate"] == candidate
    assert confirmation["original_input_digest"] == resolution["original_input_digest"]
    assert confirmation["dictionary_version"] == "liv-2.0-fixture-v1"
    assert confirmation["actor_id"] == "reviewer-001"
    assert confirmation["confirmed_at"] == "2026-07-10T08:00:00Z"
    assert dictionary == dictionary_before
    json.dumps(confirmation, ensure_ascii=False, allow_nan=False)


def test_confirmation_preserves_verbatim_unicode_whitespace_and_casing():
    original_input = {
        "facility_name": "  Ｃｏｍｍｕｎｉｔｙ  MARKET  ",
        "raw_facility_type": "  传统市集  ",
        "use_description": "固定\u3000室内市场",
    }
    dictionary = authoritative_dictionary_fixture()
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)

    confirmation = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=resolution["candidates"][0],
    )

    assert confirmation["valid"] is True
    assert confirmation["original_input"] == original_input
    assert confirmation["normalized_input"] == {
        "facility_name": "community market",
        "raw_facility_type": "传统市集",
        "use_description": "固定 室内市场",
    }

    changed_raw_input = {**original_input, "facility_name": "community market"}
    rejected = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=dictionary,
        original_input=changed_raw_input,
        selected_candidate=resolution["candidates"][0],
    )

    assert rejected["valid"] is False
    assert "original_input_digest_mismatch" in rejected["validation_errors"]


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("actor_id", "", "actor_id_missing"),
        ("confirmed_at", "2026-07-10", "confirmed_at_timezone_missing"),
        ("confirmed_at", "not-a-timestamp", "confirmed_at_invalid"),
        ("selected_standard_class_id", "facility.unknown", "selected_standard_class_not_in_dictionary"),
        ("original_input_digest", "", "original_input_digest_missing"),
        ("dictionary_version", "", "dictionary_version_missing"),
        ("dictionary_version", "liv-2.0-stale", "dictionary_version_mismatch"),
    ],
)
def test_human_confirmation_rejects_incomplete_or_stale_scope(field, value, expected_error):
    original_input = {
        "facility_name": "社区传统市集",
        "raw_facility_type": "传统市集",
        "use_description": "固定室内市场",
    }
    dictionary = authoritative_dictionary_fixture()
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)
    payload = {
        "actor_id": "reviewer-001",
        "confirmed_at": "2026-07-10T08:00:00Z",
        "selected_standard_class_id": "facility.market",
        "original_input_digest": resolution["original_input_digest"],
        "dictionary_version": "liv-2.0-fixture-v1",
    }
    payload[field] = value

    result = validate_human_confirmation(
        payload,
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=resolution["candidates"][0],
    )

    assert result["valid"] is False
    assert expected_error in result["validation_errors"]
    assert result["mutates_authoritative_dictionary"] is False


def test_human_confirmation_rejects_another_requests_input_digest():
    original_input = {
        "facility_name": "社区传统市集",
        "raw_facility_type": "传统市集",
        "use_description": "固定室内市场",
    }
    dictionary = authoritative_dictionary_fixture()
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)
    result = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": "sha256:another-request",
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=resolution["candidates"][0],
    )

    assert result["valid"] is False
    assert result["validation_errors"] == ["original_input_digest_mismatch"]


@pytest.mark.parametrize(
    ("missing_argument", "expected_error"),
    [
        ("original_input", "current_original_input_missing"),
        ("selected_candidate", "selected_candidate_evidence_missing"),
    ],
)
def test_human_confirmation_requires_current_request_and_candidate_evidence(
    missing_argument,
    expected_error,
):
    original_input = {
        "facility_name": "社区传统市集",
        "raw_facility_type": "传统市集",
        "use_description": "固定室内市场",
    }
    dictionary = authoritative_dictionary_fixture()
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)
    kwargs = {
        "dictionary": dictionary,
        "original_input": original_input,
        "selected_candidate": resolution["candidates"][0],
    }
    kwargs.pop(missing_argument)

    result = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        **kwargs,
    )

    assert result["valid"] is False
    assert expected_error in result["validation_errors"]


def test_human_confirmation_rejects_candidate_evidence_from_another_resolution():
    dictionary = authoritative_dictionary_fixture()
    original_input = {
        "facility_name": "社区传统市集",
        "raw_facility_type": "传统市集",
        "use_description": "固定室内市场",
    }
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)
    mismatched_candidate = deepcopy(resolution["candidates"][0])
    mismatched_candidate["evidence"] = [
        {
            "input_field": "facility_name",
            "matched_value": "伪造证据",
            "source_reference": "fixture://forged",
        }
    ]

    result = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=mismatched_candidate,
    )

    assert result["valid"] is False
    assert "selected_candidate_evidence_mismatch" in result["validation_errors"]


def test_human_confirmation_rejects_candidate_with_omitted_evidence():
    dictionary = authoritative_dictionary_fixture()
    original_input = {
        "facility_name": "社区传统市集",
        "raw_facility_type": "传统市集",
        "use_description": "固定室内市场",
    }
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)
    candidate_without_evidence = deepcopy(resolution["candidates"][0])
    candidate_without_evidence.pop("evidence")

    result = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=candidate_without_evidence,
    )

    assert result["valid"] is False
    assert "selected_candidate_evidence_missing" in result["validation_errors"]


def human_selected_candidate(*, class_id="facility.market", evidence=None, dictionary_version="liv-2.0-fixture-v1"):
    return {
        "standard_class_id": class_id,
        "standard_class_label": "传统市场",
        "authority_level": "human_confirmation",
        "match_method": "human_selected",
        "confidence": "human_confirmed",
        "dictionary_version": dictionary_version,
        "rule_version": None,
        "human_confirmation_required": False,
        "human_confirmed": True,
        "evidence": evidence
        if evidence is not None
        else [
            {
                "evidence_type": "reviewer_reason",
                "reason": "Reviewer verified the proposed use against the case materials.",
            }
        ],
    }


def test_human_can_confirm_unresolved_facility_with_explicit_reviewer_evidence():
    dictionary = authoritative_dictionary_fixture()
    dictionary_before = deepcopy(dictionary)
    original_input = {
        "facility_name": "新型邻里服务点",
        "raw_facility_type": "未分类设施",
        "use_description": "现场材料由审查员核验",
    }
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)
    assert resolution["resolution_status"] == "unresolved"

    selected_candidate = human_selected_candidate()
    confirmation = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=selected_candidate,
    )

    assert confirmation["valid"] is True
    assert confirmation["selected_candidate"]["match_method"] == "human_selected"
    assert confirmation["selected_candidate"]["authority_level"] == "human_confirmation"
    assert confirmation["selected_candidate"]["human_confirmed"] is True
    assert confirmation["selected_candidate"]["confidence"] == "human_confirmed"
    assert confirmation["selected_candidate"]["human_confirmation_required"] is False
    assert confirmation["selected_candidate_evidence"] == selected_candidate["evidence"]
    assert dictionary == dictionary_before


@pytest.mark.parametrize(
    ("candidate", "payload_updates", "expected_error"),
    [
        (
            human_selected_candidate(class_id="facility.unknown"),
            {"selected_standard_class_id": "facility.unknown"},
            "selected_standard_class_not_in_dictionary",
        ),
        (human_selected_candidate(evidence=[]), {}, "selected_candidate_evidence_missing"),
        (
            human_selected_candidate(dictionary_version="liv-2.0-stale"),
            {},
            "selected_candidate_dictionary_version_mismatch",
        ),
        (human_selected_candidate(), {"original_input_digest": "sha256:arbitrary"}, "original_input_digest_mismatch"),
    ],
)
def test_unresolved_human_selection_rejects_invalid_scope(candidate, payload_updates, expected_error):
    dictionary = authoritative_dictionary_fixture()
    original_input = {
        "facility_name": "新型邻里服务点",
        "raw_facility_type": "未分类设施",
        "use_description": "现场材料由审查员核验",
    }
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)
    payload = {
        "actor_id": "reviewer-001",
        "confirmed_at": "2026-07-10T08:00:00Z",
        "selected_standard_class_id": "facility.market",
        "original_input_digest": resolution["original_input_digest"],
        "dictionary_version": "liv-2.0-fixture-v1",
    }
    payload.update(payload_updates)

    confirmation = validate_human_confirmation(
        payload,
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=candidate,
    )

    assert confirmation["valid"] is False
    assert expected_error in confirmation["validation_errors"]
    assert confirmation["mutates_authoritative_dictionary"] is False


def test_unresolved_human_selection_requires_explicit_reviewer_reason():
    dictionary = authoritative_dictionary_fixture()
    original_input = {
        "facility_name": "新型邻里服务点",
        "raw_facility_type": "未分类设施",
        "use_description": "现场材料由审查员核验",
    }
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)
    candidate = human_selected_candidate(
        evidence=[{"evidence_type": "reviewer_reason", "reason": "  "}]
    )

    confirmation = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=candidate,
    )

    assert confirmation["valid"] is False
    assert "selected_candidate_reviewer_reason_missing" in confirmation["validation_errors"]


def test_human_selected_candidate_cannot_override_authoritative_resolution():
    dictionary = authoritative_dictionary_fixture()
    original_input = {
        "facility_name": "社区传统市集",
        "raw_facility_type": "传统市集",
        "use_description": "固定室内市场",
    }
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)
    assert resolution["resolution_status"] == "authoritative_confirmed"

    confirmation = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=human_selected_candidate(),
    )

    assert confirmation["valid"] is False
    assert "selected_candidate_evidence_mismatch" in confirmation["validation_errors"]


@pytest.mark.parametrize(
    "original_input",
    [
        {
            "facility_name": "",
            "raw_facility_type": "未分类设施",
            "use_description": "现场材料由审查员核验",
        },
        {
            "facility_name": "新型邻里服务点",
            "raw_facility_type": "\u3000",
            "use_description": "现场材料由审查员核验",
        },
        {
            "facility_name": "新型邻里服务点",
            "raw_facility_type": "未分类设施",
            "use_description": {},
        },
    ],
    ids=["empty", "whitespace_only", "non_string"],
)
def test_human_selected_rejects_semantically_incomplete_input(original_input):
    dictionary = authoritative_dictionary_fixture()
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)
    assert resolution["resolution_status"] == "unresolved"

    confirmation = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=human_selected_candidate(),
    )

    assert confirmation["valid"] is False
    assert "human_selected_semantic_input_incomplete" in confirmation["validation_errors"]
    assert confirmation["selected_candidate"] is None
    assert confirmation["mutates_authoritative_dictionary"] is False


@pytest.mark.parametrize(
    ("evidence", "expected_error"),
    [
        (
            [{"evidence_type": "document_reference", "reason": "Reviewed materials."}],
            "selected_candidate_reviewer_evidence_type_invalid",
        ),
        (
            [
                {
                    "evidence_type": "reviewer_reason",
                    "reason": "Reviewed materials.",
                    "note": "unexpected",
                }
            ],
            "selected_candidate_evidence_fields_invalid",
        ),
        (
            [
                {
                    "evidence_type": "reviewer_reason",
                    "reason": "Reviewed materials.",
                    "unsafe": object(),
                }
            ],
            "selected_candidate_evidence_fields_invalid",
        ),
    ],
    ids=["wrong_type", "extra_field", "unsafe_extra_value"],
)
def test_human_selected_rejects_noncanonical_reviewer_evidence(evidence, expected_error):
    dictionary = authoritative_dictionary_fixture()
    original_input = {
        "facility_name": "新型邻里服务点",
        "raw_facility_type": "未分类设施",
        "use_description": "现场材料由审查员核验",
    }
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)

    confirmation = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=human_selected_candidate(evidence=evidence),
    )

    assert confirmation["valid"] is False
    assert expected_error in confirmation["validation_errors"]
    json.dumps(confirmation, ensure_ascii=False, allow_nan=False)


def test_human_selected_sanitizes_reviewer_evidence_for_strict_json_audit():
    dictionary = authoritative_dictionary_fixture()
    original_input = {
        "facility_name": "新型邻里服务点",
        "raw_facility_type": "未分类设施",
        "use_description": "现场材料由审查员核验",
    }
    resolution = resolve_s6_facility_semantics(**original_input, dictionary=dictionary)
    candidate = human_selected_candidate(
        evidence=[
            {
                "evidence_type": "reviewer_reason",
                "reason": "  Reviewer verified the source materials.  ",
            }
        ]
    )
    candidate["unsafe_extra"] = object()

    confirmation = validate_human_confirmation(
        {
            "actor_id": "reviewer-001",
            "confirmed_at": "2026-07-10T08:00:00Z",
            "selected_standard_class_id": "facility.market",
            "original_input_digest": resolution["original_input_digest"],
            "dictionary_version": "liv-2.0-fixture-v1",
        },
        dictionary=dictionary,
        original_input=original_input,
        selected_candidate=candidate,
    )

    assert confirmation["valid"] is True
    assert confirmation["selected_candidate_evidence"] == [
        {
            "evidence_type": "reviewer_reason",
            "reason": "Reviewer verified the source materials.",
        }
    ]
    assert "unsafe_extra" not in confirmation["selected_candidate"]
    json.dumps(confirmation, ensure_ascii=False, allow_nan=False)
