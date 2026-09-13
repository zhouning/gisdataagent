"""Regression contracts for the v45 manual-acceptance issues."""

import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from data_agent.api import abu_dhabi_semantic_admin_routes as admin_routes
from data_agent.api.abu_dhabi_nl2sql_product_routes import _execution_admission
from data_agent.abu_dhabi_artifact_registry import current_artifact_path
from data_agent.governed_virtual_nl2sql import (
    detect_question_language,
    resolve_direct_metric_contract,
)


def _request(*, query: str, entry_type: str) -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": query.encode(),
            "path_params": {"entry_type": entry_type},
        },
        receive=receive,
    )


@pytest.mark.parametrize(
    "question",
    [
        "按设施类型和阶段统计设施数量。",
        "按生命周期阶段和设施类型统计宜居设施数量。",
        "按设施类型和生命周期阶段统计宜居设施的数量。",
    ],
)
def test_liveability_facility_count_is_admitted_by_published_contract(question):
    admission = _execution_admission("liveability", question)

    assert admission["runtime_admitted"] is True
    assert admission["candidate_resolution"].get("contract_id") in {
        None,
        "LIVEABILITY_FACILITY_COUNT_BY_STAGE_TYPE_V4",
    }
    semantic = json.loads(
        current_artifact_path("liveability", "semantic").read_text(encoding="utf-8")
    )
    direct = resolve_direct_metric_contract(
        question, detect_question_language(question), semantic
    )
    assert direct["status"] == "matched"
    assert direct["contract_id"] == "LIVEABILITY_FACILITY_COUNT_BY_STAGE_TYPE_V4"


@pytest.mark.asyncio
async def test_metric_contract_path_alias_is_normalized_without_relaxing_scope(monkeypatch):
    user = SimpleNamespace(identifier="analyst", metadata={"role": "analyst"})
    monkeypatch.setattr(admin_routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(admin_routes, "_set_user_context", lambda value: ("analyst", "analyst"))
    monkeypatch.setattr(admin_routes, "_engine", lambda: None)

    response = await admin_routes.semantic_admin_entries(
        _request(query="scope=liveability", entry_type="metric-contracts")
    )
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["entry_type"] == "metric_contracts"

    invalid = await admin_routes.semantic_admin_entries(
        _request(query="scope=not a scope", entry_type="metric-contracts")
    )
    assert invalid.status_code == 400
