import asyncio
import json
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent import bird_chat
from data_agent.api import bird_chat_routes
from data_agent.user_context import current_user_id, current_user_role


def test_selected_source_requires_permission_before_model(monkeypatch):
    from data_agent import bird_source, nl2sql_executor
    calls = []
    def deny(_):
        raise PermissionError("unavailable")
    monkeypatch.setattr(bird_source, "registered_database", deny)
    monkeypatch.setattr(nl2sql_executor, "run_nl2semantic2sql", lambda *a, **k: calls.append(k))
    with pytest.raises(PermissionError):
        bird_chat._run_selected_question("Count records", "sample")
    assert not calls


def test_chat_thread_retains_identity_and_uses_product_entrypoint(monkeypatch):
    from data_agent import bird_source, nl2sql_executor
    seen = []
    def execute(question, **kwargs):
        seen.append((question, current_user_id.get(), current_user_role.get(), kwargs))
        return json.dumps({"status": "ok", "sql": "SELECT COUNT(*) FROM assets"})
    monkeypatch.setattr(bird_source, "registered_database", lambda _: "bird_sample")
    monkeypatch.setattr(nl2sql_executor, "run_nl2semantic2sql", execute)
    token, role = current_user_id.set("test-owner"), current_user_role.set("analyst")
    try:
        asyncio.run(asyncio.to_thread(bird_chat._run_selected_question, "Count records", "sample"))
    finally:
        current_user_id.reset(token)
        current_user_role.reset(role)
    assert seen == [("Count records", "test-owner", "analyst", {"execution_engine": "postgis", "bird_db_id": "sample"})]


def test_source_catalog_requires_authentication(monkeypatch):
    monkeypatch.setattr(bird_chat_routes, "_get_user_from_request", lambda _: None)
    monkeypatch.setattr(bird_chat_routes, "visible_chat_sources", lambda: pytest.fail("unauthorized catalog access"))
    client = TestClient(Starlette(routes=bird_chat_routes.get_bird_chat_routes()))
    assert client.get("/api/nl2sql/bird-sources").status_code == 401


def test_source_catalog_uses_authenticated_identity(monkeypatch):
    user = SimpleNamespace(identifier="alice", metadata={"role": "analyst"})
    monkeypatch.setattr(bird_chat_routes, "_get_user_from_request", lambda _: user)
    def sources():
        assert current_user_id.get() == "alice"
        assert current_user_role.get() == "analyst"
        return [{"db_id": "sample", "label": "bird_sample", "table_count": 1}]
    monkeypatch.setattr(bird_chat_routes, "visible_chat_sources", sources)
    client = TestClient(Starlette(routes=bird_chat_routes.get_bird_chat_routes()))
    response = client.get("/api/nl2sql/bird-sources")
    assert response.status_code == 200
    assert response.json()["sources"][0]["db_id"] == "sample"


def test_presentation_discloses_preview_limit_and_never_marks_failure_success():
    report = {"status": "ok", "sql": "SELECT value FROM assets", "execution": {
        "status": "ok", "rows": 150, "columns": ["value"], "data": [{"value": "exact value"}], "truncated": False}}
    presentation = bird_chat.answer_presentation(report, "sample", "zh", 12)
    assert presentation["truncated"] is True
    assert presentation["displayed_row_count"] == 1
    assert presentation["row_count"] == 150
    assert presentation["rows"] == report["execution"]["data"]
    assert bird_chat.answer_presentation({"status": "rejected"}, "sample", "zh", 12) is None


def test_no_source_selection_preserves_existing_chat_route():
    assert asyncio.run(bird_chat.handle_bird_chat("Question", {})) is False
