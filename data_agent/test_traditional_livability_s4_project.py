from __future__ import annotations

from copy import deepcopy
import json

import pytest

from data_agent.uwm.traditional_livability_s4_project import (
    S4_PROJECT_REQUEST_SCHEMA,
    validate_s4_project_request,
)


def project_request(*, gfa=1000.0) -> dict:
    return {
        "analysis_area_id": "  fulu.heping  ",
        "planning_parcel_id": "  parcel-017  ",
        "project_name": "  和平村复合公共服务项目  ",
        "project_description": "  面向真实规划地块的多业态方案  ",
        "actor_id": "client-supplied-actor-must-not-win",
        "uses": [
            {
                "use_id": "market-use",
                "use_name": "  农贸市场  ",
                "raw_use_type": "  室内市场  ",
                "use_description": "  固定室内市场  ",
                "gfa_m2": gfa,
                "confirmed_standard_class_id": "  facility.market  ",
                "human_confirmation": {
                    "confirmed": True,
                    "note": "  规划人员确认  ",
                },
            },
            {
                "use_name": "社区服务中心",
                "raw_use_type": "社区服务",
                "use_description": "综合服务空间",
                "gfa_m2": 2000,
            },
            {
                "use_name": "文化活动室",
                "raw_use_type": "文化设施",
                "use_description": "村民文化活动",
                "gfa_m2": 4000.0,
            },
        ],
    }


def _assert_no_subjective_score(value) -> None:
    if isinstance(value, dict):
        assert not any("score" in key.lower() for key in value)
        for nested in value.values():
            _assert_no_subjective_score(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_no_subjective_score(nested)


def test_valid_project_preserves_gfa_and_exact_audit_contract():
    request = project_request()
    original = deepcopy(request)

    result = validate_s4_project_request(request, actor_id="planner-01")

    assert result["schema"] == S4_PROJECT_REQUEST_SCHEMA
    assert result["valid"] is True
    assert result["validation_errors"] == []
    assert result["actor_id"] == "planner-01"
    assert result["raw_request"] == original
    assert request == original
    assert result["normalized_request"] == {
        "analysis_area_id": "fulu.heping",
        "planning_parcel_id": "parcel-017",
        "project_name": "和平村复合公共服务项目",
        "project_description": "面向真实规划地块的多业态方案",
        "uses": [
            {
                "use_id": result["uses"][0]["use_id"],
                "use_name": "农贸市场",
                "raw_use_type": "室内市场",
                "use_description": "固定室内市场",
                "gfa_m2": 1000.0,
                "confirmed_standard_class_id": "facility.market",
                "human_confirmation": {
                    "confirmed": True,
                    "note": "规划人员确认",
                },
            },
            {
                "use_id": result["uses"][1]["use_id"],
                "use_name": "社区服务中心",
                "raw_use_type": "社区服务",
                "use_description": "综合服务空间",
                "gfa_m2": 2000.0,
                "confirmed_standard_class_id": None,
                "human_confirmation": None,
            },
            {
                "use_id": result["uses"][2]["use_id"],
                "use_name": "文化活动室",
                "raw_use_type": "文化设施",
                "use_description": "村民文化活动",
                "gfa_m2": 4000.0,
                "confirmed_standard_class_id": None,
                "human_confirmation": None,
            },
        ],
    }
    assert result["total_gfa_m2"] == 7000.0
    assert sum(row["gfa_m2"] for row in result["uses"]) == result["total_gfa_m2"]
    assert sum(row["gfa_share"] for row in result["uses"]) == 1.0
    assert [row["gfa_share"] for row in result["uses"]] == pytest.approx(
        [1 / 7, 2 / 7, 4 / 7]
    )
    assert result["content_digest"].startswith("sha256:")
    assert len(result["content_digest"]) == len("sha256:") + 64
    json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True)
    _assert_no_subjective_score(result)


def test_generated_ids_and_digest_are_stable_when_use_rows_are_reordered():
    first_request = project_request()
    second_request = project_request()
    second_request["uses"] = list(reversed(second_request["uses"]))

    first = validate_s4_project_request(first_request, actor_id="planner")
    second = validate_s4_project_request(second_request, actor_id="planner")

    assert first["valid"] is True
    assert second["valid"] is True
    assert first["project_id"] == second["project_id"]
    assert {row["use_name"]: row["use_id"] for row in first["uses"]} == {
        row["use_name"]: row["use_id"] for row in second["uses"]
    }
    assert first["content_digest"] == second["content_digest"]


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), "bad", True])
def test_invalid_gfa_fails_closed(value):
    result = validate_s4_project_request(project_request(gfa=value), actor_id="planner")

    assert result["valid"] is False
    assert result["total_gfa_m2"] is None
    assert result["uses"] == []
    assert any("gfa_m2" in error for error in result["validation_errors"])
    json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True)


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        (lambda request: request.update(project_name="  "), "project_name_missing"),
        (lambda request: request.update(uses=[]), "uses_missing"),
        (lambda request: request.update(uses=["not-an-object"]), "uses[0]_not_object"),
        (lambda request: request.update(actor_id="spoofed"), None),
    ],
)
def test_project_shape_validation_and_server_actor_override(mutation, expected_error):
    request = project_request()
    mutation(request)
    result = validate_s4_project_request(request, actor_id="authenticated-planner")

    assert result["actor_id"] == "authenticated-planner"
    if expected_error is None:
        assert result["valid"] is True
    else:
        assert result["valid"] is False
        assert expected_error in result["validation_errors"]


def test_duplicate_explicit_or_generated_use_ids_fail_closed():
    explicit = project_request()
    explicit["uses"][1]["use_id"] = "market-use"
    generated = project_request()
    generated["uses"] = [generated["uses"][1], deepcopy(generated["uses"][1])]

    for request in (explicit, generated):
        result = validate_s4_project_request(request, actor_id="planner")
        assert result["valid"] is False
        assert "duplicate_use_id" in result["validation_errors"]
        assert result["total_gfa_m2"] is None
        assert result["uses"] == []


def test_non_json_request_content_fails_closed_without_leaking_unsafe_values():
    request = project_request()
    request["project_description"] = {"unsupported": object()}

    result = validate_s4_project_request(request, actor_id="planner")

    assert result["valid"] is False
    assert "content_not_canonical_json" in result["validation_errors"]
    assert result["raw_request"] is None
    assert result["normalized_request"] is None
    assert result["content_digest"] is None
    json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True)


@pytest.mark.parametrize(
    ("extra_fields", "expected_errors"),
    [
        (
            {"subjective_score": 0.8},
            ["project_undeclared_field:subjective_score"],
        ),
        (
            {"z_extra": True, "a_extra": False},
            [
                "project_undeclared_field:a_extra",
                "project_undeclared_field:z_extra",
            ],
        ),
    ],
)
def test_project_rejects_undeclared_fields_with_exact_blockers(
    extra_fields, expected_errors
):
    request = project_request()
    request.update(extra_fields)

    result = validate_s4_project_request(request, actor_id="planner")

    assert result["valid"] is False
    assert result["validation_errors"] == expected_errors
    assert result["normalized_request"] is None
    assert result["content_digest"] is None
    json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True)


def test_use_rejects_undeclared_fields_with_exact_blockers():
    request = project_request()
    request["uses"][0]["capacity_score"] = 9
    request["uses"][0]["unknown"] = "not documented"

    result = validate_s4_project_request(request, actor_id="planner")

    assert result["valid"] is False
    assert result["validation_errors"] == [
        "uses[0].undeclared_field:capacity_score",
        "uses[0].undeclared_field:unknown",
    ]
    assert result["uses"] == []
    assert result["content_digest"] is None
    json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True)


def test_documented_client_actor_field_is_accepted_but_server_actor_wins():
    request = project_request()
    request["actor_id"] = "client-actor"

    result = validate_s4_project_request(request, actor_id="server-actor")

    assert result["valid"] is True
    assert result["actor_id"] == "server-actor"
    assert result["raw_request"]["actor_id"] == "client-actor"
    assert "actor_id" not in result["normalized_request"]

    changed_request = project_request()
    changed_request["actor_id"] = "different-client-actor"
    changed = validate_s4_project_request(changed_request, actor_id="server-actor")
    assert changed["valid"] is True
    assert changed["content_digest"] != result["content_digest"]


@pytest.mark.parametrize(
    ("gfa", "expected_error"),
    [
        (10**1000, "uses[0].gfa_m2_must_be_finite_positive_number"),
        (-10**1000, "uses[0].gfa_m2_must_be_finite_positive_number"),
    ],
)
def test_gfa_numeric_conversion_overflow_fails_closed(gfa, expected_error):
    result = validate_s4_project_request(project_request(gfa=gfa), actor_id="planner")

    assert result["valid"] is False
    assert expected_error in result["validation_errors"]
    assert result["uses"] == []
    assert result["total_gfa_m2"] is None
    assert result["content_digest"] is None
    json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True)


def test_finite_use_gfa_with_overflowing_total_fails_closed():
    request = project_request(gfa=1e308)
    request["uses"][1]["gfa_m2"] = 1e308
    request["uses"][2]["gfa_m2"] = 1e308

    result = validate_s4_project_request(request, actor_id="planner")

    assert result["valid"] is False
    assert result["validation_errors"] == ["total_gfa_m2_not_finite"]
    assert result["uses"] == []
    assert result["total_gfa_m2"] is None
    assert result["normalized_request"] is None
    assert result["content_digest"] is None
    json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True)


@pytest.mark.parametrize("location", ["project", "use"])
def test_non_string_object_keys_fail_closed_and_remain_json_safe(location):
    request = project_request()
    target = request if location == "project" else request["uses"][0]
    target[7] = "invalid JSON object key"

    result = validate_s4_project_request(request, actor_id="planner")

    assert result["valid"] is False
    assert "content_not_canonical_json" in result["validation_errors"]
    assert result["content_digest"] is None
    json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True)
