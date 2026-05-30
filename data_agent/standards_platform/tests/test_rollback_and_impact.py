"""Tests for rollback + impact_graph (Wave 7)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.derivation import link_repo
from data_agent.standards_platform.derivation.strategies.qc_rule import (
    QcRuleStrategy,
)
from data_agent.standards_platform.derivation.strategies.semantic_hint import (
    SemanticHintStrategy,
)


def _seed_bound_element(engine, ver_id, *, obligation="mandatory",
                         bound_column="zldwmc"):
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation, bound_table, bound_column) "
            "VALUES (:i, :v, :c, '名', 'string', :o, "
            " 'cq_dltb', :bc)"
        ), {"i": eid, "v": ver_id, "c": f"E-{eid[:6]}",
             "o": obligation, "bc": bound_column})
    return eid


def _cleanup_all(engine, doc_id):
    with engine.connect() as c:
        link_ids = [str(r[0]) for r in c.execute(text(
            "SELECT l.id FROM std_derived_link l "
            "JOIN std_document_version v ON v.id = l.source_version_id "
            "WHERE v.document_id=:d"
        ), {"d": doc_id}).fetchall()]
        hint_ids = [r[0] for r in c.execute(text(
            "SELECT id FROM agent_semantic_hints "
            "WHERE std_derived_link_id = ANY(CAST(:ids AS uuid[]))"
        ), {"ids": link_ids or [str(uuid.uuid4())]}).fetchall()]
        rule_ids = [r[0] for r in c.execute(text(
            "SELECT id FROM agent_quality_rules "
            "WHERE std_derived_link_id = ANY(CAST(:ids AS uuid[]))"
        ), {"ids": link_ids or [str(uuid.uuid4())]}).fetchall()]
    with engine.begin() as conn:
        if hint_ids:
            conn.execute(text(
                "DELETE FROM agent_semantic_hints WHERE id = ANY(:ids)"
            ), {"ids": hint_ids})
        if rule_ids:
            conn.execute(text(
                "DELETE FROM agent_quality_rules WHERE id = ANY(:ids)"
            ), {"ids": rule_ids})
        if link_ids:
            conn.execute(text(
                "DELETE FROM std_derived_link "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"ids": link_ids})
        conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                     {"i": doc_id})


# ---------------------------------------------------------------------------
# rollback_version
# ---------------------------------------------------------------------------

def test_rollback_marks_links_superseded(engine, fresh_clause):
    """A successful rollback flips active links to 'superseded'."""
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id, obligation="mandatory")
    SemanticHintStrategy().run(version_id=ver_id, by_user="admin")
    QcRuleStrategy().run(version_id=ver_id, by_user="admin")
    try:
        # Pre-condition: 2 active links (1 per strategy).
        with engine.connect() as c:
            n_active = c.execute(text(
                "SELECT count(*) FROM std_derived_link "
                "WHERE source_version_id=:v AND status='active'"
            ), {"v": ver_id}).scalar()
        assert n_active == 2

        summary = link_repo.rollback_version(version_id=ver_id, by_user="admin")
        # Both strategies appear in summary.
        assert "to_semantic_hint" in summary
        assert "to_qc_rule" in summary
        assert summary["to_semantic_hint"]["links_marked"] == 1
        assert summary["to_qc_rule"]["links_marked"] == 1

        # No active links remain; both are now 'superseded'.
        with engine.connect() as c:
            statuses = [r[0] for r in c.execute(text(
                "SELECT status FROM std_derived_link "
                "WHERE source_version_id=:v"
            ), {"v": ver_id}).fetchall()]
        assert all(s == "superseded" for s in statuses)
    finally:
        _cleanup_all(engine, doc_id)


def test_rollback_stales_downstream_rows(engine, fresh_clause):
    """Downstream tables that carry derived_status get flipped to 'stale'."""
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id, obligation="mandatory")
    SemanticHintStrategy().run(version_id=ver_id, by_user="admin")
    QcRuleStrategy().run(version_id=ver_id, by_user="admin")
    try:
        link_repo.rollback_version(version_id=ver_id, by_user="admin")
        with engine.connect() as c:
            hint_status = c.execute(text(
                "SELECT derived_status FROM agent_semantic_hints "
                "WHERE std_version_id=:v"
            ), {"v": ver_id}).scalar()
            rule_status = c.execute(text(
                "SELECT derived_status FROM agent_quality_rules "
                "WHERE std_version_id=:v"
            ), {"v": ver_id}).scalar()
        assert hint_status == "stale"
        assert rule_status == "stale"
    finally:
        _cleanup_all(engine, doc_id)


def test_rollback_preserves_manual_rows(engine, fresh_clause):
    """Manual rows (std_derived_link_id IS NULL) must NOT be touched."""
    cid, doc_id, ver_id = fresh_clause
    manual_hint_id = None
    try:
        with engine.begin() as conn:
            row = conn.execute(text(
                "INSERT INTO agent_semantic_hints "
                "(scope_type, scope_ref, hint_kind, hint_text_zh, severity, "
                " trigger_keywords, derived_status) "
                "VALUES ('column', 'cq_dltb.foo', 'other', 'manual hint', "
                " 'info', '[]'::jsonb, 'active') RETURNING id"
            )).first()
            manual_hint_id = row[0]

        # Roll back a version that produced no derivations — should be a no-op.
        summary = link_repo.rollback_version(version_id=ver_id, by_user="admin")
        assert summary == {}

        # Manual hint untouched.
        with engine.connect() as c:
            status = c.execute(text(
                "SELECT derived_status FROM agent_semantic_hints WHERE id=:i"
            ), {"i": manual_hint_id}).scalar()
        assert status == "active"
    finally:
        with engine.begin() as conn:
            if manual_hint_id is not None:
                conn.execute(text(
                    "DELETE FROM agent_semantic_hints WHERE id=:i"
                ), {"i": manual_hint_id})
        _cleanup_all(engine, doc_id)


def test_rollback_empty_when_nothing_active(engine, fresh_clause):
    """Re-rolling a version with no active links returns empty summary."""
    cid, doc_id, ver_id = fresh_clause
    try:
        summary = link_repo.rollback_version(version_id=ver_id, by_user="admin")
        assert summary == {}
    finally:
        _cleanup_all(engine, doc_id)


# ---------------------------------------------------------------------------
# impact_graph
# ---------------------------------------------------------------------------

def test_impact_graph_data_element_returns_all_descendants(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    eid = _seed_bound_element(engine, ver_id, obligation="mandatory")
    SemanticHintStrategy().run(version_id=ver_id, by_user="admin")
    QcRuleStrategy().run(version_id=ver_id, by_user="admin")
    try:
        impacts = link_repo.impact_graph(
            source_kind="data_element", source_id=eid,
        )
        # 1 hint + 1 rule = 2 active descendants.
        assert len(impacts) == 2
        strategies = {i["derivation_strategy"] for i in impacts}
        assert strategies == {"to_semantic_hint", "to_qc_rule"}
        target_kinds = {i["target_kind"] for i in impacts}
        assert target_kinds == {"semantic_hint", "qc_rule"}
    finally:
        _cleanup_all(engine, doc_id)


def test_impact_graph_clause_walks_through_data_element(engine, fresh_clause):
    """Clause source_kind expands to its data_elements + their links."""
    cid, doc_id, ver_id = fresh_clause
    # Bind the data_element to the clause so the walk hits it.
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation, bound_table, bound_column, "
            "defined_by_clause_id) "
            "VALUES (:i, :v, 'E', 'n', 'string', 'mandatory', "
            " 'cq_dltb', 'zldwmc', :c)"
        ), {"i": eid, "v": ver_id, "c": cid})
    QcRuleStrategy().run(version_id=ver_id, by_user="admin")
    try:
        impacts = link_repo.impact_graph(
            source_kind="clause", source_id=cid,
        )
        assert len(impacts) == 1
        assert impacts[0]["derivation_strategy"] == "to_qc_rule"
    finally:
        _cleanup_all(engine, doc_id)


def test_impact_graph_excludes_stale_by_default(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    eid = _seed_bound_element(engine, ver_id, obligation="mandatory")
    QcRuleStrategy().run(version_id=ver_id, by_user="admin")
    try:
        # Verify active baseline.
        impacts = link_repo.impact_graph(
            source_kind="data_element", source_id=eid,
        )
        assert len(impacts) == 1

        # Roll back → active=0, superseded=1.
        link_repo.rollback_version(version_id=ver_id, by_user="admin")

        # Default (active only) should now be empty.
        impacts = link_repo.impact_graph(
            source_kind="data_element", source_id=eid,
        )
        assert len(impacts) == 0

        # include_stale=True surfaces superseded rows too.
        impacts = link_repo.impact_graph(
            source_kind="data_element", source_id=eid, include_stale=True,
        )
        assert len(impacts) == 1
        assert impacts[0]["status"] == "superseded"
    finally:
        _cleanup_all(engine, doc_id)
