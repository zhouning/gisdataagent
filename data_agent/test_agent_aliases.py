import pytest
from unittest.mock import patch, MagicMock


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
