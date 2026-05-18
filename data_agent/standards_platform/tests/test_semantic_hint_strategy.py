"""Tests for SemanticHintStrategy."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.derivation.strategies.semantic_hint import (
    SemanticHintStrategy,
)


def _seed_bound_element(engine, ver_id, *, name_zh="测试列", code=None,
                        bound_table="cq_dltb", bound_column="dlbm",
                        datatype="string", obligation="optional"):
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation, bound_table, bound_column) "
            "VALUES (:i, :v, :c, :n, :dt, :ob, :bt, :bc)"
        ), {"i": eid, "v": ver_id, "c": code or f"E-{eid[:6]}",
             "n": name_zh, "dt": datatype, "ob": obligation,
             "bt": bound_table, "bc": bound_column})
    return eid


def _cleanup(engine, doc_id, *, hint_ids=None, link_ids=None):
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
        conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                     {"i": doc_id})


def _collect_artefacts(engine, version_id):
    """Return (hint_ids, link_ids) for cleanup."""
    with engine.connect() as c:
        hint_ids = [r[0] for r in c.execute(text(
            "SELECT id FROM agent_semantic_hints WHERE std_version_id=:v"
        ), {"v": version_id}).fetchall()]
        link_ids = [str(r[0]) for r in c.execute(text(
            "SELECT id FROM std_derived_link WHERE source_version_id=:v"
        ), {"v": version_id}).fetchall()]
    return hint_ids, link_ids


def test_happy_n_elements_n_hints_n_links(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    eids = [
        _seed_bound_element(engine, ver_id, name_zh="地类编码",
                            bound_column="dlbm"),
        _seed_bound_element(engine, ver_id, name_zh="图斑面积",
                            bound_column="tbmj"),
    ]
    s = SemanticHintStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    hint_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(result.new_links) == 2
        assert len(result.failed) == 0
        assert len(hint_ids) == 2
        assert len(link_ids) == 2
    finally:
        _cleanup(engine, doc_id, hint_ids=hint_ids, link_ids=link_ids)


def test_skip_unbound_elements(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    # Bound + unbound mix
    _seed_bound_element(engine, ver_id, name_zh="bound")
    unbound_eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation) "
            "VALUES (:i, :v, 'UNBND', '未绑定', 'string', 'optional')"
        ), {"i": unbound_eid, "v": ver_id})

    s = SemanticHintStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    hint_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(result.new_links) == 1
    finally:
        _cleanup(engine, doc_id, hint_ids=hint_ids, link_ids=link_ids)


def test_preserve_manual_hint(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    eid = _seed_bound_element(engine, ver_id, name_zh="Test 测试",
                              bound_table="manual_table",
                              bound_column="manual_col")

    # Insert a manual hint with same scope_ref + hint_kind + hint_text_zh
    # std_derived_link_id IS NULL → must NOT be touched.
    with engine.begin() as conn:
        manual_row = conn.execute(text(
            "INSERT INTO agent_semantic_hints "
            "(scope_type, scope_ref, hint_kind, hint_text_zh, severity, "
            " trigger_keywords) "
            "VALUES ('column', 'manual_table.manual_col', 'other', "
            " '标准定义：Test 测试（类型 string，optional）', 'info', "
            " CAST('[]' AS jsonb)) RETURNING id"
        )).first()
        manual_hint_id = manual_row[0]

    try:
        s = SemanticHintStrategy()
        result = s.run(version_id=ver_id, by_user="admin")
        # Strategy should detect manual row and skip — no new derived link.
        assert len(result.new_links) == 0
        # Manual row still has std_derived_link_id IS NULL
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT std_derived_link_id, derived_status FROM agent_semantic_hints "
                "WHERE id=:i"
            ), {"i": manual_hint_id}).first()
        assert row[0] is None
        assert row[1] is None
    finally:
        hint_ids, link_ids = _collect_artefacts(engine, ver_id)
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM agent_semantic_hints WHERE id=:i"),
                         {"i": manual_hint_id})
        _cleanup(engine, doc_id, hint_ids=hint_ids, link_ids=link_ids)


def test_idempotent_rerun(engine, fresh_clause):
    """Run strategy twice on same version — second should not create dup."""
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id, name_zh="重复测试")
    s = SemanticHintStrategy()
    s.run(version_id=ver_id, by_user="admin")
    hint_ids_1, link_ids_1 = _collect_artefacts(engine, ver_id)

    s.run(version_id=ver_id, by_user="admin")
    hint_ids_2, link_ids_2 = _collect_artefacts(engine, ver_id)

    try:
        # Same hint, same content → 1 row total. Second run creates a fresh
        # link (old one stale via "superseded by re-derive"). hint count = 1.
        assert len(hint_ids_2) == 1
        # Active link count: only 1 (old went stale).
        with engine.connect() as c:
            n_active = c.execute(text(
                "SELECT count(*) FROM std_derived_link "
                "WHERE source_version_id=:v AND status='active'"
            ), {"v": ver_id}).scalar()
        assert n_active == 1
    finally:
        _cleanup(engine, doc_id, hint_ids=hint_ids_2, link_ids=link_ids_2)


def test_stale_flow_across_fork(engine, fresh_clause):
    """v1 derives 2 hints; fork v2 deletes 1 element + redrives → old link stale."""
    cid, doc_id, ver_id = fresh_clause
    e1 = _seed_bound_element(engine, ver_id, name_zh="保留", bound_column="keep")
    e2 = _seed_bound_element(engine, ver_id, name_zh="删除", bound_column="drop")

    s = SemanticHintStrategy()
    r1 = s.run(version_id=ver_id, by_user="admin")
    assert len(r1.new_links) == 2

    # Simulate v2 by creating new version + only e1's data_element.
    v2 = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document_version (id, document_id, version_label, "
            "status, semver_major, semver_minor) "
            "VALUES (:i, :d, 'v2.0', 'draft', 2, 0)"
        ), {"i": v2, "d": doc_id})
    _seed_bound_element(engine, v2, name_zh="保留", bound_column="keep")
    # NOTE: 'drop' element NOT carried into v2.

    r2 = s.run(version_id=v2, by_user="admin")
    try:
        # New v2 link for "keep"; old v1 "drop" link should be staled.
        assert len(r2.staled_links) >= 1
        # The "drop" hint row should have derived_status='stale'.
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT derived_status FROM agent_semantic_hints "
                "WHERE scope_ref='cq_dltb.drop'"
            )).first()
        assert row is not None
        assert row[0] == "stale"
    finally:
        v1_hints, v1_links = _collect_artefacts(engine, ver_id)
        v2_hints, v2_links = _collect_artefacts(engine, v2)
        _cleanup(engine, doc_id, hint_ids=v1_hints + v2_hints,
                 link_ids=v1_links + v2_links)


def test_trigger_keywords_includes_column_and_name(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id, name_zh="地类",
                         bound_column="dlbm")
    s = SemanticHintStrategy()
    s.run(version_id=ver_id, by_user="admin")
    hint_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT trigger_keywords FROM agent_semantic_hints "
                "WHERE id=:i"
            ), {"i": hint_ids[0]}).first()
        kws = row[0]
        assert "dlbm" in kws
        assert "地类" in kws
    finally:
        _cleanup(engine, doc_id, hint_ids=hint_ids, link_ids=link_ids)


def test_source_tag_includes_version(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id)
    s = SemanticHintStrategy()
    s.run(version_id=ver_id, by_user="admin")
    hint_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        with engine.connect() as c:
            tag = c.execute(text(
                "SELECT source_tag FROM agent_semantic_hints WHERE id=:i"
            ), {"i": hint_ids[0]}).scalar()
        assert tag == f"std:v{ver_id}"
    finally:
        _cleanup(engine, doc_id, hint_ids=hint_ids, link_ids=link_ids)


def test_link_status_active_and_target_id_matches(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element(engine, ver_id)
    s = SemanticHintStrategy()
    s.run(version_id=ver_id, by_user="admin")
    hint_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT status, target_id, target_kind, target_table, "
                "derivation_strategy "
                "FROM std_derived_link WHERE id=:i"
            ), {"i": link_ids[0]}).first()
        assert row[0] == "active"
        assert row[1] == str(hint_ids[0])
        assert row[2] == "semantic_hint"
        assert row[3] == "agent_semantic_hints"
        assert row[4] == "to_semantic_hint"
    finally:
        _cleanup(engine, doc_id, hint_ids=hint_ids, link_ids=link_ids)
