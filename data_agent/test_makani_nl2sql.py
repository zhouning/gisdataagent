import hashlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from data_agent.abu_dhabi_artifact_registry import current_artifact_path
from data_agent.makani_nl2sql import (
    SEMANTIC_LAYER_PATH,
    SOURCE_ID,
    SOURCE_OWNER,
    describe_makani_nl2sql_request,
    format_makani_nl2sql_response,
    resolve_makani_nl2sql_request,
    run_makani_nl2sql_request,
)

REPO_ROOT = SEMANTIC_LAYER_PATH.parents[3]
V1_SEMANTIC_PATH = SEMANTIC_LAYER_PATH.with_name("makani_semantic_layer_v1.json")
BENCHMARK_PATH = SEMANTIC_LAYER_PATH.with_name("makani_free_form_benchmark_v1.json")
ONTOLOGY_PATH = SEMANTIC_LAYER_PATH.with_name("makani_ontology_v1.json")


@pytest.mark.parametrize(
    ("question", "language"),
    [
        ("按生命周期状态和材质统计配水主管数量", "zh"),
        ("Count telecom structures by category and inventory status", "en"),
        ("احسب صمامات الري حسب الحالة وحالة الأصل", "ar"),
    ],
)
def test_makani_source_route_accepts_multilingual_questions(question, language):
    request = resolve_makani_nl2sql_request(f"@Makani {question}")

    assert request is not None
    assert request.accepted is True
    assert request.question == question
    assert request.language == language
    assert request.explicit_source_selection is True


def test_makani_selected_source_keeps_plain_follow_up():
    request = resolve_makani_nl2sql_request(
        "再按状态拆分",
        continue_selected_source=True,
    )

    assert request is not None and request.accepted
    assert request.explicit_source_selection is False
    assert resolve_makani_nl2sql_request("普通问题") is None


def test_makani_selected_source_does_not_capture_another_explicit_scope():
    request = resolve_makani_nl2sql_request(
        "@Liveability 按阶段统计设施数量",
        continue_selected_source=True,
    )

    assert request is None


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [("clarify", "需要澄清，未执行 SQL"), ("refuse", "已拒绝执行，未执行 SQL")],
)
def test_makani_rejected_response_exposes_manual_validation_outcome(outcome, expected):
    request = resolve_makani_nl2sql_request("@Makani 统计建筑")
    assert request is not None

    response = format_makani_nl2sql_response(
        request,
        {"status": "rejected", "outcome": outcome, "reason": "policy_boundary"},
    )

    assert expected in response
    assert "policy_boundary" in response


def test_makani_rejected_response_exposes_structured_table_options():
    request = resolve_makani_nl2sql_request("@Makani Count centers")
    assert request is not None
    response = format_makani_nl2sql_response(
        request,
        {
            "status": "rejected",
            "outcome": "clarify",
            "reason": "semantic_binding_gate:multiple_semantic_bindings",
            "clarification": {
                "required": True,
                "options": [{"physical_table": "public.poi_a"}],
            },
        },
    )
    assert "Available tables" in response
    assert "public.poi_a" in response


def test_makani_success_response_exposes_full_result_equivalence_fingerprint():
    request = resolve_makani_nl2sql_request("@Makani 统计建筑数量")
    assert request is not None
    fingerprint = "b" * 64
    response = format_makani_nl2sql_response(
        request,
        {
            "status": "ok",
            "result": {
                "row_count": 1,
                "displayed_row_count": 1,
                "columns": ["building_count"],
                "data": [{"building_count": 9}],
                "equivalence_fingerprints": {
                    "unordered_position_numeric6_fingerprint": fingerprint
                },
            },
            "query": {"sql": "SELECT 9 AS building_count"},
        },
    )

    assert "结果等价指纹" in response
    assert fingerprint in response


@pytest.mark.asyncio
async def test_makani_route_uses_shared_configured_model(monkeypatch):
    monkeypatch.setenv("GDA_LLM_MODEL", "gemini-3.7-flash")
    request = resolve_makani_nl2sql_request(
        "@Makani Count water main pipes by lifecycle status and material"
    )
    assert request is not None and request.accepted
    runner = AsyncMock(return_value={"status": "ok"})
    deployed_semantic_path = current_artifact_path("makani", "semantic")
    with (
        patch("data_agent.makani_nl2sql.run_governed_virtual_nl2sql", runner),
        patch(
            "data_agent.makani_nl2sql.current_artifact_path",
            return_value=deployed_semantic_path,
        ),
    ):
        report = await run_makani_nl2sql_request(request, timeout_seconds=42)

    assert report == {"status": "ok"}
    runner.assert_awaited_once_with(
        question=request.question,
        semantic_layer_path=deployed_semantic_path,
        source_id=SOURCE_ID,
        owner=SOURCE_OWNER,
        model_name="gemini-3.7-flash",
        reasoning_effort="medium",
        timeout_seconds=42,
        execution_profile="baseline_sql",
    )


def test_makani_response_and_metadata_are_governed_and_secret_free():
    request = resolve_makani_nl2sql_request(
        "@Makani Count water main pipes by lifecycle status and material"
    )
    assert request is not None and request.accepted
    report = {
        "status": "ok",
        "semantic_version": "abu-dhabi-makani-v3",
        "metric_contract_version": "abu-dhabi-makani-inventory-v3",
        "prompt": {"version": "governed-virtual-nl2semantic2sql-v1.2"},
        "query": {
            "sql": "SELECT lifecyclestatus, subtype, COUNT(*) FROM public.adwea_w_mainpipe",
            "sql_sha256": "sql-sha",
            "semantic_metric_contract": {
                "contract_id": "MAKANI_INVENTORY_ADWEA_W_MAINPIPE_V3",
                "application": "governed_table_local_inventory",
            },
        },
        "result": {
            "row_count": 1,
            "displayed_row_count": 1,
            "columns": ["lifecyclestatus", "subtype", "row_count"],
            "data": [{"lifecyclestatus": "Active", "subtype": "DI", "row_count": 7}],
        },
    }

    response = format_makani_nl2sql_response(request, report)
    metadata = describe_makani_nl2sql_request(request, report)

    assert "makani_sync_full/public" in response
    assert "public.adwea_w_mainpipe" in response
    assert metadata["source_id"] == 13
    assert metadata["semantic_version"] == "abu-dhabi-makani-v3"
    assert metadata["applied_metric_contract_id"] == ("MAKANI_INVENTORY_ADWEA_W_MAINPIPE_V3")
    assert "sql" not in metadata
    assert "data" not in metadata


def test_makani_v1_artifacts_cover_ten_tables_and_frozen_gold():
    if not all(path.is_file() for path in (V1_SEMANTIC_PATH, ONTOLOGY_PATH, BENCHMARK_PATH)):
        pytest.skip("customer deployment fixtures are not included in the public repository")
    semantic = json.loads(V1_SEMANTIC_PATH.read_text(encoding="utf-8"))
    ontology = json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))
    benchmark = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))

    tables = {item["physical_table"] for item in semantic["table_bindings"]}
    assert semantic["activation_gate"]["active_for_free_form_nl2sql"] is True
    assert semantic["source_binding"]["source_id"] == 13
    assert len(tables) == 10
    assert len(semantic["metric_contracts"]) == 10
    assert len(ontology["concepts"]) == 10
    assert ontology["relations"] == []
    assert benchmark["coverage"] == {
        "gold_intent_count": 10,
        "gold_language_run_count": 30,
        "refusal_case_count": 6,
        "total_case_count": 36,
        "source_rows_persisted": False,
    }
    assert len(benchmark["cases"]) == 36

    query_cases = [case for case in benchmark["cases"] if case["expected"]["status"] == "ok"]
    assert {case["expected"]["tables"][0] for case in query_cases} == tables
    for case in query_cases:
        reference = case["expected"]["gold_result_contract"]
        path = REPO_ROOT / reference["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == reference["sha256"]
        contract = json.loads(path.read_text(encoding="utf-8"))
        assert contract["source_contract"]["source_id"] == 13
        assert contract["source_contract"]["authorized_schema"] == "layer"
        assert contract["expected_result"]["row_count"] < 1000
        assert "rows" not in contract["expected_result"]
