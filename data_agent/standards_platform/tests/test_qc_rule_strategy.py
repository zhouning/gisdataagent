"""Tests for QcRuleStrategy (Wave 7 — to_qc_rule)."""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.derivation.strategies.qc_rule import (
    QcRuleStrategy,
)


def _seed_value_domain(engine, ver_id, *, kind="enumeration",
                       code="LANDUSE_L1", name="一级地类",
                       items: list[tuple] | None = None) -> str:
    vid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_value_domain (id, document_version_id, code, "
            "name, kind) VALUES (:i, :v, :c, :n, :k)"
        ), {"i": vid, "v": ver_id, "c": code, "n": name, "k": kind})
        if items:
            for ordinal, (val, lbl) in enumerate(items):
                conn.execute(text(
                    "INSERT INTO std_value_domain_item (id, value_domain_id, "
                    "value, label_zh, ordinal) "
                    "VALUES (:i, :v, :val, :lbl, :o)"
                ), {"i": str(uuid.uuid4()), "v": vid, "val": val, "lbl": lbl,
                     "o": ordinal})
    return vid


def _seed_element(engine, ver_id, *, name_zh="测试列",
                  bound_table="cq_dltb", bound_column="dlbm",
                  obligation="optional", value_domain_id=None) -> str:
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation, bound_table, bound_column, "
            "value_domain_id) "
            "VALUES (:i, :v, :c, :n, 'string', :ob, :bt, :bc, :vd)"
        ), {"i": eid, "v": ver_id, "c": f"E-{eid[:6]}", "n": name_zh,
             "ob": obligation, "bt": bound_table, "bc": bound_column,
             "vd": value_domain_id})
    return eid


def _collect_artefacts(engine, version_id):
    with engine.connect() as c:
        rule_ids = [r[0] for r in c.execute(text(
            "SELECT id FROM agent_quality_rules WHERE std_version_id=:v"
        ), {"v": version_id}).fetchall()]
        link_ids = [str(r[0]) for r in c.execute(text(
            "SELECT id FROM std_derived_link "
            "WHERE source_version_id=:v AND derivation_strategy='to_qc_rule'"
        ), {"v": version_id}).fetchall()]
    return rule_ids, link_ids


def _cleanup(engine, doc_id, *, rule_ids=None, link_ids=None):
    with engine.begin() as conn:
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


def test_mandatory_emits_completeness_rule(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, obligation="mandatory",
                  bound_column="zldwmc", name_zh="坐落单位名称")
    s = QcRuleStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    rule_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(result.new_links) == 1
        assert len(result.failed) == 0
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT rule_name, rule_type, config, severity, "
                "       derived_status, is_shared "
                "FROM agent_quality_rules WHERE id=:i"
            ), {"i": rule_ids[0]}).first()
        assert row[0] == "std:cq_dltb.zldwmc:completeness"
        assert row[1] == "completeness"
        cfg = row[2] if isinstance(row[2], dict) else json.loads(row[2])
        assert cfg["fields"] == ["zldwmc"]
        assert row[3] == "HIGH"
        assert row[4] == "active"
        assert row[5] is True
    finally:
        _cleanup(engine, doc_id, rule_ids=rule_ids, link_ids=link_ids)


def test_enumeration_emits_field_check(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    vd_id = _seed_value_domain(
        engine, ver_id, kind="enumeration",
        items=[("0101", "水田"), ("0102", "水浇地")],
    )
    _seed_element(engine, ver_id, obligation="optional",
                  bound_column="dlbm", name_zh="地类编码",
                  value_domain_id=vd_id)
    s = QcRuleStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    rule_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(result.new_links) == 1
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT rule_type, config, severity FROM agent_quality_rules "
                "WHERE id=:i"
            ), {"i": rule_ids[0]}).first()
        assert row[0] == "field_check"
        cfg = row[1] if isinstance(row[1], dict) else json.loads(row[1])
        assert cfg["field"] == "dlbm"
        assert cfg["allowed_values"] == ["0101", "0102"]
        assert row[2] == "MEDIUM"
    finally:
        _cleanup(engine, doc_id, rule_ids=rule_ids, link_ids=link_ids)


def test_mandatory_with_enum_emits_two_rules(engine, fresh_clause):
    """A mandatory element with a value_domain → completeness + field_check."""
    cid, doc_id, ver_id = fresh_clause
    vd_id = _seed_value_domain(
        engine, ver_id, kind="enumeration",
        items=[("0101", "水田")],
    )
    _seed_element(engine, ver_id, obligation="mandatory",
                  bound_column="dlbm", name_zh="地类编码",
                  value_domain_id=vd_id)
    s = QcRuleStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    rule_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(result.new_links) == 2
        with engine.connect() as c:
            types = {r[0] for r in c.execute(text(
                "SELECT rule_type FROM agent_quality_rules "
                "WHERE id = ANY(:ids)"
            ), {"ids": rule_ids}).fetchall()}
        assert types == {"completeness", "field_check"}
    finally:
        _cleanup(engine, doc_id, rule_ids=rule_ids, link_ids=link_ids)


def test_pattern_emits_field_check_with_regex(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    vd_id = _seed_value_domain(
        engine, ver_id, kind="pattern", code="DLBM_FMT", name="编码格式",
        items=[(r"^\d{4}$", "四位数字")],
    )
    _seed_element(engine, ver_id, obligation="optional",
                  bound_column="dlbm", name_zh="地类编码",
                  value_domain_id=vd_id)
    s = QcRuleStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    rule_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(result.new_links) == 1
        with engine.connect() as c:
            cfg = c.execute(text(
                "SELECT config FROM agent_quality_rules WHERE id=:i"
            ), {"i": rule_ids[0]}).scalar()
        cfg = cfg if isinstance(cfg, dict) else json.loads(cfg)
        assert cfg["regex"] == r"^\d{4}$"
    finally:
        _cleanup(engine, doc_id, rule_ids=rule_ids, link_ids=link_ids)


def test_optional_without_domain_skipped(engine, fresh_clause):
    """An optional element with no value_domain → 0 rules."""
    cid, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, obligation="optional",
                  bound_column="zldwmc", value_domain_id=None)
    s = QcRuleStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    rule_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(result.new_links) == 0
        assert rule_ids == []
    finally:
        _cleanup(engine, doc_id, rule_ids=rule_ids, link_ids=link_ids)


def test_rerun_idempotent(engine, fresh_clause):
    """Same version re-run → same rule rows, only one active link per target."""
    cid, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, obligation="mandatory",
                  bound_column="zldwmc")
    s = QcRuleStrategy()
    s.run(version_id=ver_id, by_user="admin")
    s.run(version_id=ver_id, by_user="admin")  # re-run
    rule_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(rule_ids) == 1
        with engine.connect() as c:
            active = c.execute(text(
                "SELECT COUNT(*) FROM std_derived_link "
                "WHERE source_version_id=:v "
                "  AND derivation_strategy='to_qc_rule' "
                "  AND status='active'"
            ), {"v": ver_id}).scalar()
        assert active == 1
    finally:
        _cleanup(engine, doc_id, rule_ids=rule_ids, link_ids=link_ids)


def test_manual_row_not_overwritten(engine, fresh_clause):
    """A manual rule (std_derived_link_id IS NULL) sharing the deterministic
    rule_name must be left alone."""
    cid, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, obligation="mandatory",
                  bound_column="zldwmc")
    expected_name = "std:cq_dltb.zldwmc:completeness"
    manual_id = None
    try:
        with engine.begin() as conn:
            row = conn.execute(text(
                "INSERT INTO agent_quality_rules "
                "(rule_name, rule_type, config, owner_username) "
                "VALUES (:n, 'completeness', '{\"fields\":[\"manual\"]}'::jsonb, "
                "        'admin') RETURNING id"
            ), {"n": expected_name}).first()
            manual_id = row[0]

        s = QcRuleStrategy()
        # by_user='admin' → owner_username='admin' → collides with manual row.
        result = s.run(version_id=ver_id, by_user="admin")
        assert len(result.new_links) == 0
        with engine.connect() as c:
            link_col = c.execute(text(
                "SELECT std_derived_link_id, config FROM agent_quality_rules "
                "WHERE id=:i"
            ), {"i": manual_id}).first()
        assert link_col[0] is None  # untouched
        cfg = link_col[1] if isinstance(link_col[1], dict) else json.loads(link_col[1])
        assert cfg["fields"] == ["manual"]  # body preserved
    finally:
        with engine.begin() as conn:
            if manual_id is not None:
                conn.execute(text(
                    "DELETE FROM agent_quality_rules WHERE id=:i"
                ), {"i": manual_id})
        _cleanup(engine, doc_id)


def test_supersede_marks_stale(engine, fresh_clause):
    """A new version of the same document removes an element → prior rule
    keeps existing but its link becomes stale and derived_status='stale'."""
    cid, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, obligation="mandatory",
                  bound_column="zldwmc")
    s = QcRuleStrategy()
    s.run(version_id=ver_id, by_user="admin")

    # Spawn a v2 of the same document with NO bound elements.
    ver2_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) "
            "VALUES (:i, :d, 'v2.0', 'draft', 2)"
        ), {"i": ver2_id, "d": doc_id})

    s.run(version_id=ver2_id, by_user="admin")

    rule_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        # The original rule row remains (history preserved) but is now stale.
        with engine.connect() as c:
            status = c.execute(text(
                "SELECT derived_status FROM agent_quality_rules WHERE id=:i"
            ), {"i": rule_ids[0]}).scalar()
        assert status == "stale"
        with engine.connect() as c:
            link_status = c.execute(text(
                "SELECT status FROM std_derived_link WHERE id=:i"
            ), {"i": link_ids[0]}).scalar()
        assert link_status == "stale"
    finally:
        _cleanup(engine, doc_id, rule_ids=rule_ids, link_ids=link_ids)
