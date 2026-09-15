from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from data_agent import liveability_execution_profile_promotion as promotion
from data_agent.api.abu_dhabi_nl2sql_product_routes import product_execute


def _execute_request(body: dict) -> Request:
    payload = json.dumps(body).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/abu-dhabi/nl2semantic2sql/execute",
            "headers": [],
            "query_string": b"",
        },
        receive=receive,
    )


def test_current_liveability_promotion_binds_to_the_deployed_semantic_artifact() -> None:
    approved = promotion.load_liveability_execution_profile_promotion()

    assert approved["status"] == "approved"
    assert approved["authorization"]["source_id"] == 12
    assert approved["authorization"]["default_execution_profile"] == (
        "semantic_ir_experimental"
    )
    assert promotion.resolve_liveability_default_execution_profile() == (
        "semantic_ir_experimental"
    )


def test_default_profile_falls_back_when_promotion_record_is_unavailable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(promotion, "PROMOTION_PATH", tmp_path / "missing-promotion.json")

    assert promotion.resolve_liveability_default_execution_profile() == "baseline_sql"


def test_default_profile_falls_back_when_current_semantic_artifact_drifts(monkeypatch) -> None:
    current = promotion.current_artifact_manifest("liveability")
    drifted = copy.deepcopy(current)
    drifted["artifacts"]["semantic"]["sha256"] = "0" * 64
    monkeypatch.setattr(
        promotion,
        "current_artifact_manifest",
        lambda source_key: drifted,
    )

    assert promotion.resolve_liveability_default_execution_profile() == "baseline_sql"


@pytest.mark.asyncio
async def test_public_execute_uses_approved_default_and_rejects_client_profile_switch(monkeypatch) -> None:
    user = SimpleNamespace(identifier="test-user", metadata={"role": "analyst"})
    monkeypatch.setattr(
        "data_agent.api.abu_dhabi_nl2sql_product_routes._get_user_from_request",
        lambda request: user,
    )
    monkeypatch.setattr(
        "data_agent.api.abu_dhabi_nl2sql_product_routes._set_user_context",
        lambda value: ("test-user", "analyst"),
    )
    monkeypatch.setattr(
        "data_agent.api.abu_dhabi_nl2sql_product_routes._execution_admission",
        lambda scope, question: {"runtime_admitted": True},
    )
    captured = {}

    async def fake_run(request, *, owner, execution_profile, verify_platform_schema):
        captured["execution_profile"] = execution_profile
        return {"status": "ok", "source_rows_persisted": False}

    monkeypatch.setattr("data_agent.liveability_nl2sql.run_liveability_nl2sql_request", fake_run)

    response = await product_execute(
        _execute_request(
            {"scope": "liveability", "question": "按生命周期阶段统计宜居设施数量。"}
        )
    )
    rejected = await product_execute(
        _execute_request(
            {
                "scope": "liveability",
                "question": "按生命周期阶段统计宜居设施数量。",
                "execution_profile": "baseline_sql",
            }
        )
    )

    assert response.status_code == 200
    assert captured["execution_profile"] == "semantic_ir_experimental"
    assert rejected.status_code == 400
