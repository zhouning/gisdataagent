import pytest
from unittest.mock import patch, MagicMock
from starlette.requests import Request


def _fake_engine_with_result(rows):
    engine = MagicMock()
    conn = MagicMock()
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    conn.execute.return_value = result
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value = conn
    engine.begin.return_value = conn
    return engine, conn


def test_list_aliases_returns_user_rows():
    from data_agent.api.agent_management_routes import list_aliases_for_user
    engine, conn = _fake_engine_with_result([
        {"handle": "DataExploration", "aliases": ["数据探查"], "display_name": "数据探查", "pinned": True, "hidden": False}
    ])
    with patch("data_agent.api.agent_management_routes.get_engine", return_value=engine):
        result = list_aliases_for_user("alice")
    assert len(result) == 1
    assert result[0]["handle"] == "DataExploration"
    assert result[0]["aliases"] == ["数据探查"]
    assert result[0]["pinned"] is True


def test_upsert_alias_inserts_or_updates():
    from data_agent.api.agent_management_routes import upsert_alias
    engine, conn = _fake_engine_with_result([])
    with patch("data_agent.api.agent_management_routes.get_engine", return_value=engine):
        upsert_alias("alice", "DataExploration", aliases=["数据探查", "探查"], display_name="数据探查智能体")
    call_args = conn.execute.call_args
    sql_text = str(call_args[0][0])
    assert "INSERT INTO agent_aliases" in sql_text
    assert "ON CONFLICT" in sql_text


def test_set_flag_pin_updates_row():
    from data_agent.api.agent_management_routes import set_flag
    engine, conn = _fake_engine_with_result([])
    with patch("data_agent.api.agent_management_routes.get_engine", return_value=engine):
        set_flag("alice", "DataExploration", "pinned", True)
    call_args = conn.execute.call_args
    sql_text = str(call_args[0][0])
    assert "INSERT INTO agent_aliases" in sql_text
    assert "pinned" in sql_text


def test_list_aliases_no_engine_returns_empty():
    from data_agent.api.agent_management_routes import list_aliases_for_user
    with patch("data_agent.api.agent_management_routes.get_engine", return_value=None):
        assert list_aliases_for_user("alice") == []


def test_build_registry_merges_aliases_from_db():
    from data_agent import mention_registry
    fake_aliases = [{
        "handle": "DataExploration",
        "aliases": ["数据探查", "探查"],
        "display_name": "数据探查",
        "pinned": True,
        "hidden": False,
    }]
    with patch("data_agent.mention_registry._load_user_aliases", return_value=fake_aliases):
        registry = mention_registry.build_registry(user_id="alice", role="analyst")
    target = next(t for t in registry if t["handle"] == "DataExploration")
    assert target["aliases"] == ["数据探查", "探查"]
    assert target["display_name"] == "数据探查"
    assert target["pinned"] is True
    assert target["hidden"] is False


def test_build_registry_no_db_aliases_defaults():
    from data_agent import mention_registry
    with patch("data_agent.mention_registry._load_user_aliases", return_value=[]):
        registry = mention_registry.build_registry(user_id="alice", role="analyst")
    target = next(t for t in registry if t["handle"] == "DataExploration")
    assert target["aliases"] == []
    assert target["pinned"] is False
    assert target["hidden"] is False


def test_lookup_matches_alias():
    from data_agent import mention_registry
    registry = [{
        "handle": "DataExploration",
        "aliases": ["数据探查", "探查"],
        "display_name": "数据探查",
        "pinned": False, "hidden": False,
        "type": "sub_agent",
    }]
    assert mention_registry.lookup(registry, "数据探查")["handle"] == "DataExploration"
    assert mention_registry.lookup(registry, "探查")["handle"] == "DataExploration"
    assert mention_registry.lookup(registry, "DataExploration")["handle"] == "DataExploration"
    assert mention_registry.lookup(registry, "nonexistent") is None


def test_lookup_handle_takes_priority_over_alias():
    from data_agent import mention_registry
    registry = [
        {"handle": "A", "aliases": ["shared"], "display_name": "", "pinned": False, "hidden": False, "type": "sub_agent"},
        {"handle": "B", "aliases": ["shared"], "display_name": "shared", "pinned": False, "hidden": False, "type": "sub_agent"},
        {"handle": "shared", "aliases": [], "display_name": "", "pinned": False, "hidden": False, "type": "sub_agent"},
    ]
    assert mention_registry.lookup(registry, "shared")["handle"] == "shared"


import asyncio
from typing import Optional


def _make_request(path: str, method: str = "GET", body=None, path_params=None):
    """Build a minimal Starlette Request for handler unit tests."""
    import json as _json
    scope = {
        "type": "http", "method": method, "path": path,
        "headers": [], "query_string": b"", "path_params": path_params or {},
    }
    body_bytes = _json.dumps(body).encode() if body else b""
    async def receive():
        return {"type": "http.request", "body": body_bytes, "more_body": False}
    return Request(scope, receive=receive)


class _FakeUser:
    def __init__(self, identifier="alice", role="analyst"):
        self.identifier = identifier
        self.metadata = {"role": role}


def test_mention_targets_api_excludes_hidden():
    from data_agent.api.agent_management_routes import _api_mention_targets
    fake_registry = [
        {"handle": "A", "label": "A", "type": "sub_agent", "description": "",
         "aliases": [], "display_name": "", "pinned": False, "hidden": False,
         "allowed_roles": ["analyst"], "required_state_keys": [], "pipeline": "GENERAL"},
        {"handle": "B", "label": "B", "type": "sub_agent", "description": "",
         "aliases": [], "display_name": "", "pinned": False, "hidden": True,
         "allowed_roles": ["analyst"], "required_state_keys": [], "pipeline": "GENERAL"},
    ]
    with patch("data_agent.api.agent_management_routes._get_user_from_request", return_value=_FakeUser()), \
         patch("data_agent.api.agent_management_routes.build_registry", return_value=fake_registry):
        resp = asyncio.run(_api_mention_targets(_make_request("/api/agents/mention-targets")))
    import json
    data = json.loads(resp.body.decode())
    handles = [t["handle"] for t in data["targets"]]
    assert "A" in handles
    assert "B" not in handles


def test_mention_targets_api_include_hidden_flag():
    from data_agent.api.agent_management_routes import _api_mention_targets
    fake_registry = [
        {"handle": "A", "label": "A", "type": "sub_agent", "description": "",
         "aliases": [], "display_name": "", "pinned": False, "hidden": True,
         "allowed_roles": ["analyst"], "required_state_keys": [], "pipeline": "GENERAL"},
    ]
    scope = {
        "type": "http", "method": "GET", "path": "/api/agents/mention-targets",
        "headers": [], "query_string": b"include_hidden=1", "path_params": {},
    }
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    req = Request(scope, receive=receive)
    with patch("data_agent.api.agent_management_routes._get_user_from_request", return_value=_FakeUser()), \
         patch("data_agent.api.agent_management_routes.build_registry", return_value=fake_registry):
        resp = asyncio.run(_api_mention_targets(req))
    import json
    data = json.loads(resp.body.decode())
    assert len(data["targets"]) == 1


def test_set_alias_api_calls_upsert():
    from data_agent.api.agent_management_routes import _api_set_alias
    req = _make_request("/api/agents/DataExploration/alias", method="PUT",
                        body={"aliases": ["探查"], "display_name": "数据探查"},
                        path_params={"handle": "DataExploration"})
    with patch("data_agent.api.agent_management_routes._get_user_from_request", return_value=_FakeUser()), \
         patch("data_agent.api.agent_management_routes.upsert_alias") as mock_upsert:
        resp = asyncio.run(_api_set_alias(req))
    assert resp.status_code == 200
    mock_upsert.assert_called_once_with("alice", "DataExploration", aliases=["探查"], display_name="数据探查")


def test_set_pin_api_calls_set_flag():
    from data_agent.api.agent_management_routes import _api_set_pin
    req = _make_request("/api/agents/DataExploration/pin", method="PUT",
                        body={"pinned": True}, path_params={"handle": "DataExploration"})
    with patch("data_agent.api.agent_management_routes._get_user_from_request", return_value=_FakeUser()), \
         patch("data_agent.api.agent_management_routes.set_flag") as mock_flag:
        resp = asyncio.run(_api_set_pin(req))
    assert resp.status_code == 200
    mock_flag.assert_called_once_with("alice", "DataExploration", "pinned", True)


def test_unauthorized_returns_401():
    from data_agent.api.agent_management_routes import _api_mention_targets
    req = _make_request("/api/agents/mention-targets")
    with patch("data_agent.api.agent_management_routes._get_user_from_request", return_value=None):
        resp = asyncio.run(_api_mention_targets(req))
    assert resp.status_code == 401
