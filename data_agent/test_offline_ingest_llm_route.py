from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from data_agent.api import offline_ingest_routes as routes
from data_agent.openai_compatible_llm import LLMServiceError


def _request(payload: dict) -> Request:
    body = json.dumps(payload).encode("utf-8")
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/offline-ingest/semantic-query",
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "client": ("test", 1234),
            "server": ("test", 8000),
            "scheme": "http",
        },
        receive,
    )


@pytest.mark.asyncio
async def test_semantic_query_does_not_fallback_when_local_llm_is_unavailable(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("GDA_OFFLINE_INGEST_AUTH_REQUIRED", "false")
    projection = tmp_path / "semantic_projection.json"
    projection.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(routes, "_projection_path", lambda _store, _id: projection)
    monkeypatch.setattr(
        "data_agent.dltb_multi_engine_query._current_catalog_source",
        lambda *_args: {"execution_bindings": {"lake": {}}},
    )

    def fail(*args, **kwargs):
        raise LLMServiceError("ollama unavailable")

    monkeypatch.setattr("data_agent.dltb_multi_engine_query.query_dltb_with_llm", fail)
    response = await routes.semantic_query(
        _request(
            {
                "projection_id": "p",
                "question": "各地类面积是多少？",
                "execution_engine": "geopandas",
            }
        )
    )
    assert response.status_code == 503
    payload = json.loads(response.body)
    assert payload["code"] == "local_llm_unavailable"
    assert payload["fallback_used"] is False


@pytest.mark.asyncio
async def test_semantic_query_defaults_to_postgis(monkeypatch, tmp_path):
    monkeypatch.setenv("GDA_OFFLINE_INGEST_AUTH_REQUIRED", "false")
    projection = tmp_path / "semantic_projection.json"
    projection.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(routes, "_projection_path", lambda _store, _id: projection)
    captured = {}

    def fake_query(_projection, _question, *, execution_engine, limit):
        captured.update(engine=execution_engine, limit=limit)
        return {"status": "succeeded", "rows": []}

    monkeypatch.setattr("data_agent.dltb_multi_engine_query.query_dltb", fake_query)
    response = await routes.semantic_query(
        _request({"projection_id": "p", "question": "图斑有多少条？"})
    )

    assert response.status_code == 200
    assert captured == {"engine": "postgis", "limit": 100}
