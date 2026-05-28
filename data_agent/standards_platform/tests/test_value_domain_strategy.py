"""Tests for ValueDomainStrategy (Wave 6-eng).

Mirrors the structure of test_semantic_hint_strategy.py: per-test seed-then-
cleanup using the shared `engine` and `fresh_clause` fixtures from conftest.
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.derivation.strategies.value_domain import (
    ValueDomainStrategy,
)


def _seed_value_domain(engine, ver_id, *, kind="enumeration",
                       code="LANDUSE_L1", name="一级地类",
                       items: list[tuple] | None = None) -> str:
    """Insert std_value_domain + items, return value_domain_id (uuid str)."""
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


def _seed_bound_element_with_domain(engine, ver_id, *, name_zh="测试列",
                                     bound_table="cq_dltb",
                                     bound_column="dlbm",
                                     value_domain_id=None):
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation, bound_table, bound_column, "
            "value_domain_id) "
            "VALUES (:i, :v, :c, :n, 'string', 'mandatory', :bt, :bc, :vd)"
        ), {"i": eid, "v": ver_id, "c": f"E-{eid[:6]}", "n": name_zh,
             "bt": bound_table, "bc": bound_column, "vd": value_domain_id})
    return eid


def _collect_artefacts(engine, version_id):
    """Return (hint_ids, link_ids) for a given version."""
    with engine.connect() as c:
        hint_ids = [r[0] for r in c.execute(text(
            "SELECT id FROM agent_semantic_hints WHERE std_version_id=:v"
        ), {"v": version_id}).fetchall()]
        link_ids = [str(r[0]) for r in c.execute(text(
            "SELECT id FROM std_derived_link WHERE source_version_id=:v"
        ), {"v": version_id}).fetchall()]
    return hint_ids, link_ids


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


def test_enumeration_emits_value_enum_hint(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    vd_id = _seed_value_domain(
        engine, ver_id, kind="enumeration",
        items=[("0101", "水田"), ("0102", "水浇地"), ("0103", "旱地")],
    )
    eid = _seed_bound_element_with_domain(
        engine, ver_id, name_zh="地类编码", bound_column="dlbm",
        value_domain_id=vd_id,
    )
    s = ValueDomainStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    hint_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(result.new_links) == 1
        assert len(result.failed) == 0
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT hint_kind, hint_text_zh, trigger_keywords "
                "FROM agent_semantic_hints WHERE id=:i"
            ), {"i": hint_ids[0]}).first()
        assert row[0] == "value_enum"
        assert "水田" in row[1]
        assert "0101" in row[1]
        # trigger keywords should include enum values to catch literal
        # mentions in user questions.
        kws = row[2] if isinstance(row[2], list) else json.loads(row[2])
        assert "dlbm" in kws
        assert "地类编码" in kws
        assert "水田" in kws
    finally:
        _cleanup(engine, doc_id, hint_ids=hint_ids, link_ids=link_ids)


def test_range_emits_value_range_hint(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    vd_id = _seed_value_domain(
        engine, ver_id, kind="range", code="AREA_RANGE", name="面积范围",
        items=[("0", "下界 ≥ 0"), ("1e10", "上界 < 100亿")],
    )
    _seed_bound_element_with_domain(
        engine, ver_id, name_zh="图斑面积", bound_column="tbmj",
        value_domain_id=vd_id,
    )
    s = ValueDomainStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    hint_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(result.new_links) == 1
        with engine.connect() as c:
            kind = c.execute(text(
                "SELECT hint_kind FROM agent_semantic_hints WHERE id=:i"
            ), {"i": hint_ids[0]}).scalar()
        assert kind == "value_range"
    finally:
        _cleanup(engine, doc_id, hint_ids=hint_ids, link_ids=link_ids)


def test_pattern_emits_value_pattern_hint(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    vd_id = _seed_value_domain(
        engine, ver_id, kind="pattern", code="DLBM_FMT", name="编码格式",
        items=[(r"^\d{4}$", "四位数字")],
    )
    _seed_bound_element_with_domain(
        engine, ver_id, name_zh="地类编码", bound_column="dlbm",
        value_domain_id=vd_id,
    )
    s = ValueDomainStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    hint_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(result.new_links) == 1
        with engine.connect() as c:
            kind, txt = c.execute(text(
                "SELECT hint_kind, hint_text_zh FROM agent_semantic_hints "
                "WHERE id=:i"
            ), {"i": hint_ids[0]}).first()
        assert kind == "value_pattern"
        assert r"^\d{4}$" in txt
    finally:
        _cleanup(engine, doc_id, hint_ids=hint_ids, link_ids=link_ids)


def test_external_codelist_emits_value_codelist_hint(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    vd_id = _seed_value_domain(
        engine, ver_id, kind="external_codelist",
        code="GBT21010", name="GB/T 21010 地类代码",
        items=[("GB/T 21010-2017 一二级类", None)],
    )
    _seed_bound_element_with_domain(
        engine, ver_id, name_zh="地类编码", bound_column="dlbm",
        value_domain_id=vd_id,
    )
    s = ValueDomainStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    hint_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(result.new_links) == 1
        with engine.connect() as c:
            kind, txt = c.execute(text(
                "SELECT hint_kind, hint_text_zh FROM agent_semantic_hints "
                "WHERE id=:i"
            ), {"i": hint_ids[0]}).first()
        assert kind == "value_codelist"
        assert "GB/T 21010" in txt
    finally:
        _cleanup(engine, doc_id, hint_ids=hint_ids, link_ids=link_ids)


def test_skip_elements_without_value_domain(engine, fresh_clause):
    """Elements with value_domain_id=NULL must be ignored entirely."""
    cid, doc_id, ver_id = fresh_clause
    _seed_bound_element_with_domain(
        engine, ver_id, name_zh="无值域", bound_column="zldwmc",
        value_domain_id=None,
    )
    s = ValueDomainStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    hint_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        assert len(result.new_links) == 0
        assert len(hint_ids) == 0
    finally:
        _cleanup(engine, doc_id, hint_ids=hint_ids, link_ids=link_ids)


def test_rerun_idempotent_same_text(engine, fresh_clause):
    """Same domain → same hint_text → existing row updated, no duplicates."""
    cid, doc_id, ver_id = fresh_clause
    vd_id = _seed_value_domain(
        engine, ver_id, kind="enumeration",
        items=[("0101", "水田")],
    )
    _seed_bound_element_with_domain(
        engine, ver_id, name_zh="地类编码", bound_column="dlbm",
        value_domain_id=vd_id,
    )
    s = ValueDomainStrategy()
    s.run(version_id=ver_id, by_user="admin")
    s.run(version_id=ver_id, by_user="admin")  # idempotent re-run
    hint_ids, link_ids = _collect_artefacts(engine, ver_id)
    try:
        # Exactly 1 hint; possibly 2 links (old marked stale + new active).
        assert len(hint_ids) == 1
        with engine.connect() as c:
            active_links = c.execute(text(
                "SELECT COUNT(*) FROM std_derived_link "
                "WHERE source_version_id=:v AND status='active'"
            ), {"v": ver_id}).scalar()
        assert active_links == 1
    finally:
        _cleanup(engine, doc_id, hint_ids=hint_ids, link_ids=link_ids)


def test_manual_row_not_overwritten(engine, fresh_clause):
    """A manual row (std_derived_link_id IS NULL) with the same UNIQUE key
    must be left alone — strategy returns no new link for that element."""
    cid, doc_id, ver_id = fresh_clause
    vd_id = _seed_value_domain(
        engine, ver_id, kind="enumeration",
        items=[("0101", "水田")],
    )
    _seed_bound_element_with_domain(
        engine, ver_id, name_zh="地类编码", bound_column="dlbm",
        value_domain_id=vd_id,
    )
    # Construct the exact hint_text_zh the strategy would produce so the
    # UNIQUE index collides:
    expected_text = "标准取值范围（一级地类）：枚举 0101=水田"

    manual_id = None
    with engine.begin() as conn:
        row = conn.execute(text(
            "INSERT INTO agent_semantic_hints "
            "(scope_type, scope_ref, hint_kind, hint_text_zh, severity, "
            " trigger_keywords) "
            "VALUES ('column', 'cq_dltb.dlbm', 'value_enum', :ht, "
            " 'info', CAST('[]' AS jsonb)) RETURNING id"
        ), {"ht": expected_text}).first()
        manual_id = row[0]
    try:
        s = ValueDomainStrategy()
        result = s.run(version_id=ver_id, by_user="admin")
        # Strategy should detect manual collision and skip — 0 new links.
        assert len(result.new_links) == 0
        with engine.connect() as c:
            still_manual = c.execute(text(
                "SELECT std_derived_link_id FROM agent_semantic_hints "
                "WHERE id=:i"
            ), {"i": manual_id}).scalar()
        assert still_manual is None  # untouched
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM agent_semantic_hints WHERE id=:i"
            ), {"i": manual_id})
        _cleanup(engine, doc_id)
