import json
from unittest.mock import AsyncMock, patch

import pytest

from data_agent.liveability_nl2sql import (
    SEMANTIC_LAYER_PATH,
    SOURCE_ID,
    SOURCE_OWNER,
    describe_liveability_nl2sql_request,
    format_liveability_nl2sql_response,
    resolve_liveability_nl2sql_request,
    run_liveability_nl2sql_request,
)
from data_agent.abu_dhabi_artifact_registry import current_artifact_path


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("统计每个行政区的当前人口", "zh"),
        ("List the five facility types with the most facilities", "en"),
        ("اعرض متوسط درجة جودة الحياة لكل منطقة", "ar"),
    ],
)
def test_explicit_source_route_accepts_arbitrary_questions(question, language):
    request = resolve_liveability_nl2sql_request(f"@Liveability {question}")

    assert request is not None
    assert request.accepted is True
    assert request.question == question
    assert request.language == language
    assert request.explicit_source_selection is True


def test_selected_source_keeps_plain_follow_up_on_product_route():
    request = resolve_liveability_nl2sql_request(
        "再按阶段拆分",
        continue_selected_source=True,
    )

    assert request is not None
    assert request.accepted is True
    assert request.explicit_source_selection is False
    assert resolve_liveability_nl2sql_request("普通问题") is None


def test_selected_source_does_not_capture_another_explicit_scope():
    request = resolve_liveability_nl2sql_request(
        "@Makani 按状态统计建筑数量",
        continue_selected_source=True,
    )

    assert request is None


def test_empty_source_selection_returns_localized_input_request():
    request = resolve_liveability_nl2sql_request("@Liveability")

    assert request is not None
    assert request.accepted is False
    assert "Enter a question" in format_liveability_nl2sql_response(request, {})


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("clarify", "需要澄清，未执行 SQL"), ("refuse", "已拒绝执行，未执行 SQL")],
)
def test_rejected_response_exposes_manual_validation_outcome(outcome, expected):
    request = resolve_liveability_nl2sql_request("@Liveability 统计设施")
    assert request is not None

    response = format_liveability_nl2sql_response(
        request,
        {"status": "rejected", "outcome": outcome, "reason": "policy_boundary"},
    )

    assert expected in response
    assert "policy_boundary" in response


def test_rejected_response_exposes_structured_table_options():
    request = resolve_liveability_nl2sql_request("@Liveability Count centers")
    assert request is not None
    response = format_liveability_nl2sql_response(
        request,
        {
            "status": "rejected",
            "outcome": "clarify",
            "reason": "semantic_binding_gate:multiple_semantic_bindings",
            "clarification": {
                "required": True,
                "options": [
                    {"physical_table": "public.poi_a", "semantic_asset_id": "asset.a"},
                    {"physical_table": "public.poi_b", "semantic_asset_id": "asset.b"},
                ],
            },
        },
    )
    assert "Available tables" in response
    assert "public.poi_a" in response
    assert "public.poi_b" in response


def test_event_metadata_exposes_non_sensitive_contract_audit_fields():
    request = resolve_liveability_nl2sql_request(
        "@Liveability Summarize liveability scores by municipality and stage"
    )
    assert request is not None and request.accepted
    report = {
        "status": "ok",
        "semantic_version": "abu-dhabi-liveability-v1",
        "metric_contract_version": "abu-dhabi-liveability-metric-projections-v1",
        "prompt": {
            "version": "governed-virtual-nl2semantic2sql-v1.2",
            "sha256": "prompt-sha",
        },
        "query": {
            "sql": "SELECT secret_model_sql",
            "sql_sha256": "executed-sql-sha",
            "semantic_metric_contract": {
                "metric_contract_version": ("abu-dhabi-liveability-metric-projections-v1"),
                "contract_id": "liveability_score_summary_by_municipality_stage",
                "application": "projection_grouping_canonicalization",
                "model_sql_sha256": "model-sql-sha",
                "canonical_sql_sha256": "canonical-sql-sha",
            },
        },
        "result": {"row_count": 3, "data": [{"sensitive": "source row"}]},
    }

    metadata = describe_liveability_nl2sql_request(request, report)

    assert metadata["prompt_version"] == ("governed-virtual-nl2semantic2sql-v1.2")
    assert metadata["metric_contract_version"] == ("abu-dhabi-liveability-metric-projections-v1")
    assert metadata["applied_metric_contract_id"] == (
        "liveability_score_summary_by_municipality_stage"
    )
    assert metadata["metric_contract_application_type"] == ("projection_grouping_canonicalization")
    assert metadata["sql_sha256"] == "executed-sql-sha"
    assert "sql" not in metadata
    assert "prompt_sha256" not in metadata
    assert "model_sql_sha256" not in metadata
    assert "data" not in metadata


def test_event_metadata_exposes_clarification_without_source_rows():
    request = resolve_liveability_nl2sql_request("@Liveability Count centers")
    assert request is not None
    metadata = describe_liveability_nl2sql_request(
        request,
        {
            "status": "rejected",
            "clarification": {
                "required": True,
                "options": [{"physical_table": "public.poi_a"}],
            },
        },
    )
    assert metadata["question"] == "Count centers"
    assert metadata["clarification"]["required"] is True
    assert "data" not in metadata


def test_event_metadata_records_contract_version_when_no_projection_applies():
    request = resolve_liveability_nl2sql_request("@Liveability Count facilities")
    assert request is not None and request.accepted

    metadata = describe_liveability_nl2sql_request(
        request,
        {
            "status": "ok",
            "metric_contract_version": ("abu-dhabi-liveability-metric-projections-v1"),
            "prompt": {
                "version": "governed-virtual-nl2semantic2sql-v1.2",
            },
            "query": {"sql_sha256": "executed-sql-sha"},
            "result": {"row_count": 1},
        },
    )

    assert metadata["metric_contract_version"] == ("abu-dhabi-liveability-metric-projections-v1")
    assert metadata["applied_metric_contract_id"] is None
    assert metadata["metric_contract_application_type"] is None


@pytest.mark.asyncio
async def test_liveability_route_uses_shared_configured_model(monkeypatch):
    monkeypatch.setenv("GDA_LLM_MODEL", "gemini-3.7-flash")
    request = resolve_liveability_nl2sql_request(
        "@Liveability How many facilities are in each stage?"
    )
    assert request is not None and request.accepted
    runner = AsyncMock(return_value={"status": "ok"})
    with patch(
        "data_agent.liveability_nl2sql.run_governed_virtual_nl2sql",
        runner,
    ):
        report = await run_liveability_nl2sql_request(request, timeout_seconds=42)

    assert report == {"status": "ok"}
    semantic_path = current_artifact_path("liveability", "semantic")
    assert semantic_path.is_file()
    assert "semantic_layer" in semantic_path.name
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    assert semantic["table_card_publication"]["status"] == "published"
    assert (
        semantic["current_version_scope_publication"]["status"]
        == "published_current_source_audited"
    )
    runner.assert_awaited_once_with(
        question=request.question,
        semantic_layer_path=current_artifact_path("liveability", "semantic"),
        source_id=SOURCE_ID,
        owner=SOURCE_OWNER,
        model_name="gemini-3.7-flash",
        reasoning_effort="medium",
        timeout_seconds=42,
        execution_profile="baseline_sql",
    )


@pytest.mark.parametrize("language", ["zh", "en", "ar"])
def test_success_response_stays_in_question_language(language):
    questions = {
        "zh": "统计设施数量",
        "en": "Count facilities",
        "ar": "احسب عدد المرافق",
    }
    request = resolve_liveability_nl2sql_request(f"@Liveability {questions[language]}")
    assert request is not None
    report = {
        "status": "ok",
        "result": {
            "row_count": 1,
            "displayed_row_count": 1,
            "truncated_for_display": False,
            "columns": ["facility_count"],
            "data": [{"facility_count": 7}],
        },
        "query": {"sql": "SELECT COUNT(*) AS facility_count FROM public.dim_facilities"},
        "semantic_caveats": [],
    }

    response = format_liveability_nl2sql_response(request, report)

    expected = {
        "zh": "查询完成",
        "en": "Query completed",
        "ar": "اكتمل الاستعلام",
    }[language]
    assert expected in response
    assert "facility_count" in response
    assert "public.dim_facilities" in response
    assert "liveability_data_20260730/public" in response


def test_success_response_exposes_full_result_equivalence_fingerprint():
    request = resolve_liveability_nl2sql_request("@Liveability 统计设施数量")
    assert request is not None
    fingerprint = "a" * 64
    response = format_liveability_nl2sql_response(
        request,
        {
            "status": "ok",
            "result": {
                "row_count": 1,
                "displayed_row_count": 1,
                "columns": ["facility_count"],
                "data": [{"facility_count": 7}],
                "equivalence_fingerprints": {
                    "unordered_position_numeric6_fingerprint": fingerprint
                },
            },
            "query": {"sql": "SELECT 7 AS facility_count"},
        },
    )

    assert "结果等价指纹" in response
    assert fingerprint in response
