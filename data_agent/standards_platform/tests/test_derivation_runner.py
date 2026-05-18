"""Tests for derivation/runner.py + handlers.py outbox wiring."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.derivation import runner
from data_agent.standards_platform import handlers as std_handlers


def _seed_bound_element(engine, ver_id):
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation, bound_table, bound_column) "
            "VALUES (:i, :v, :c, '名', 'string', 'optional', "
            " 'cq_dltb', 'col')"
        ), {"i": eid, "v": ver_id, "c": f"E-{eid[:6]}"})
    return eid


def _cleanup(engine, ver_id):
    with engine.connect() as c:
        hint_ids = [r[0] for r in c.execute(text(
            "SELECT id FROM agent_semantic_hints WHERE std_version_id=:v"
        ), {"v": ver_id}).fetchall()]
        link_ids = [str(r[0]) for r in c.execute(text(
            "SELECT id FROM std_derived_link WHERE source_version_id=:v"
        ), {"v": ver_id}).fetchall()]
    with engine.begin() as conn:
        if hint_ids:
            conn.execute(text(
                "DELETE FROM agent_semantic_hints WHERE id = ANY(:ids)"
            ), {"ids": hint_ids})
        if link_ids:
            conn.execute(text(
                "DELETE FROM std_derived_link "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"ids": link_ids})


def test_get_strategy_status_lists_six(engine):
    statuses = runner.get_strategy_status()
    names = {s["name"] for s in statuses}
    assert "to_semantic_hint" in names
    assert "to_synonym" in names
    active_names = {s["name"] for s in statuses if s["status"] == "active"}
    coming_names = {s["name"] for s in statuses if s["status"] == "coming_soon"}
    assert active_names == {"to_semantic_hint"}
    assert len(coming_names) == 5


def test_dispatch_runs_active_strategy(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id)
    try:
        results = runner.dispatch(version_id=ver_id, by_user="admin")
        assert "to_semantic_hint" in results
        assert results["to_semantic_hint"]["ok"] is True
        assert results["to_semantic_hint"]["new"] == 1
        # Coming-soon strategies aren't run
        assert "to_synonym" not in results
    finally:
        _cleanup(engine, ver_id)


def test_dispatch_with_strategies_filter(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id)
    try:
        results = runner.dispatch(
            version_id=ver_id, strategies=["to_synonym"]
        )
        # to_synonym is coming_soon → not in active, results empty
        assert results == {}
    finally:
        _cleanup(engine, ver_id)


def test_dispatch_isolates_strategy_failure(engine, fresh_clause, monkeypatch):
    """A failing strategy doesn't block others."""
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id)

    class BoomStrategy:
        name = "boom"
        def run(self, *, version_id, by_user):
            raise RuntimeError("kaboom")

    # Inject a fake strategy alongside the real one
    monkeypatch.setitem(runner._REGISTRY, "boom", BoomStrategy())
    try:
        results = runner.dispatch(version_id=ver_id, by_user="admin")
        # Both strategies attempted; boom failed but to_semantic_hint succeeded.
        assert results["boom"]["ok"] is False
        assert "kaboom" in results["boom"]["error"]
        assert results["to_semantic_hint"]["ok"] is True
    finally:
        _cleanup(engine, ver_id)


def test_handlers_dispatch_routes_version_released(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id)
    try:
        std_handlers.dispatch({
            "event_type": "version_released",
            "payload": {"version_id": ver_id},
            "id": "test-evt",
            "attempts": 0,
        })
        # Should have produced a derived link
        with engine.connect() as c:
            n_links = c.execute(text(
                "SELECT count(*) FROM std_derived_link "
                "WHERE source_version_id=:v AND status='active'"
            ), {"v": ver_id}).scalar()
        assert n_links == 1
    finally:
        _cleanup(engine, ver_id)
