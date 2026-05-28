"""Tests for SynonymStrategy (Wave 6+)."""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.derivation.strategies.synonym import (
    SynonymStrategy,
)


# Use a name no other test will touch so concurrent runs don't fight.
_TEST_TABLE_A = "test_synonym_strategy_table_A"
_TEST_TABLE_B = "test_synonym_strategy_table_B"


@pytest.fixture
def semantic_sources(engine):
    """Seed two physical-table source rows; cleanup at end."""
    ids = []
    with engine.begin() as conn:
        for tname in (_TEST_TABLE_A, _TEST_TABLE_B):
            row = conn.execute(text(
                "INSERT INTO agent_semantic_sources "
                "(table_name, display_name, description, owner_username) "
                "VALUES (:t, :d, '', 'test_synonym_strategy') "
                "RETURNING id"
            ), {"t": tname, "d": tname}).first()
            ids.append(row[0])
    yield {tname: tid for tname, tid in zip((_TEST_TABLE_A, _TEST_TABLE_B), ids)}
    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM agent_semantic_sources WHERE id = ANY(:ids)"
        ), {"ids": ids})


def _seed_data_element(engine, ver_id, *, name_zh, name_en=None,
                        bound_table=None, bound_column="col1",
                        clause_id=None):
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, name_en, datatype, obligation, bound_table, "
            "bound_column, defined_by_clause_id) "
            "VALUES (:i, :v, :c, :nz, :ne, 'string', 'optional', :bt, :bc, :cid)"
        ), {"i": eid, "v": ver_id, "c": f"E-{eid[:6]}", "nz": name_zh,
             "ne": name_en, "bt": bound_table, "bc": bound_column,
             "cid": clause_id})
    return eid


def _seed_term(engine, ver_id, *, name_zh, name_en=None,
                aliases=None, clause_id=None):
    tid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_term (id, document_version_id, term_code, "
            "name_zh, name_en, aliases, defined_by_clause_id) "
            "VALUES (:i, :v, :c, :nz, :ne, :al, :cid)"
        ), {"i": tid, "v": ver_id, "c": f"T-{tid[:6]}", "nz": name_zh,
             "ne": name_en, "al": aliases or [], "cid": clause_id})
    return tid


def _cleanup(engine, doc_id, source_ids):
    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM std_derived_link "
            "WHERE target_id = ANY(:tids) AND target_kind='synonym'"
        ), {"tids": [str(s) for s in source_ids]})
        conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                     {"i": doc_id})


def _read_synonyms(engine, source_id):
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT derived_synonyms FROM agent_semantic_sources WHERE id=:i"
        ), {"i": source_id}).first()
    val = row[0]
    if isinstance(val, str):
        val = json.loads(val)
    return val


def test_data_element_contributes_to_bound_table(engine, fresh_clause,
                                                  semantic_sources):
    cid, doc_id, ver_id = fresh_clause
    _seed_data_element(engine, ver_id, name_zh="地类编码", name_en="Land Class Code",
                        bound_table=_TEST_TABLE_A)
    try:
        s = SynonymStrategy()
        result = s.run(version_id=ver_id, by_user="admin")
        assert len(result.new_links) == 1
        syns = _read_synonyms(engine, semantic_sources[_TEST_TABLE_A])
        assert "地类编码" in syns
        assert "Land Class Code" in syns
    finally:
        _cleanup(engine, doc_id, semantic_sources.values())


def test_term_contributes_via_clause_anchor(engine, fresh_clause,
                                             semantic_sources):
    """A term defined by a clause that also has a bound data_element gets
    its name+aliases pushed onto that table's synonyms.

    A-plan: 1 link per touched table even with N contributing sources;
    term's contribution lives in derived_synonyms only.
    """
    cid, doc_id, ver_id = fresh_clause
    _seed_data_element(engine, ver_id, name_zh="图斑面积",
                        bound_table=_TEST_TABLE_A, clause_id=cid)
    _seed_term(engine, ver_id, name_zh="图斑", name_en="Plot",
               aliases=["地块", "地斑"], clause_id=cid)
    try:
        s = SynonymStrategy()
        result = s.run(version_id=ver_id, by_user="admin")
        # A-plan: 1 link per target table (anchor = first data_element)
        assert len(result.new_links) == 1
        syns = _read_synonyms(engine, semantic_sources[_TEST_TABLE_A])
        assert "图斑面积" in syns          # from data_element
        assert "图斑" in syns               # from term name_zh
        assert "Plot" in syns               # from term name_en
        assert "地块" in syns               # from term alias
        assert "地斑" in syns
    finally:
        _cleanup(engine, doc_id, semantic_sources.values())


def test_term_without_clause_anchor_skipped(engine, fresh_clause,
                                             semantic_sources):
    """Term whose clause has no bound data_element does not contribute."""
    cid, doc_id, ver_id = fresh_clause
    # data_element on table A but on a DIFFERENT clause
    other_clause_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_clause (id, document_id, document_version_id, "
            "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
            "CAST('1.1' AS ltree), '1.1', 'clause', 'body')"
        ), {"i": other_clause_id, "d": doc_id, "v": ver_id})
    _seed_data_element(engine, ver_id, name_zh="地类编码",
                        bound_table=_TEST_TABLE_A,
                        clause_id=other_clause_id)
    # Term anchored to the BASE clause cid which has no bound element
    _seed_term(engine, ver_id, name_zh="术语孤儿", clause_id=cid)
    try:
        s = SynonymStrategy()
        result = s.run(version_id=ver_id, by_user="admin")
        # only data_element, no term link
        assert len(result.new_links) == 1
        syns = _read_synonyms(engine, semantic_sources[_TEST_TABLE_A])
        assert "地类编码" in syns
        assert "术语孤儿" not in syns
    finally:
        _cleanup(engine, doc_id, semantic_sources.values())


def test_data_element_for_unknown_table_skipped(engine, fresh_clause,
                                                  semantic_sources):
    """If bound_table doesn't exist in agent_semantic_sources, skip silently."""
    cid, doc_id, ver_id = fresh_clause
    _seed_data_element(engine, ver_id, name_zh="孤儿元素",
                        bound_table="this_table_does_not_exist")
    try:
        s = SynonymStrategy()
        result = s.run(version_id=ver_id, by_user="admin")
        assert len(result.new_links) == 0
    finally:
        _cleanup(engine, doc_id, semantic_sources.values())


def test_two_tables_independent(engine, fresh_clause, semantic_sources):
    """data_elements bound to different tables do not cross-contaminate.

    A-plan: 2 tables → 2 links (1 per target).
    """
    cid, doc_id, ver_id = fresh_clause
    _seed_data_element(engine, ver_id, name_zh="A 字段",
                        bound_table=_TEST_TABLE_A)
    _seed_data_element(engine, ver_id, name_zh="B 字段",
                        bound_table=_TEST_TABLE_B)
    try:
        s = SynonymStrategy()
        result = s.run(version_id=ver_id, by_user="admin")
        assert len(result.new_links) == 2
        syns_a = _read_synonyms(engine, semantic_sources[_TEST_TABLE_A])
        syns_b = _read_synonyms(engine, semantic_sources[_TEST_TABLE_B])
        assert "A 字段" in syns_a
        assert "A 字段" not in syns_b
        assert "B 字段" in syns_b
        assert "B 字段" not in syns_a
    finally:
        _cleanup(engine, doc_id, semantic_sources.values())


def test_rerun_idempotent(engine, fresh_clause, semantic_sources):
    """Re-running with same input yields same derived_synonyms + 1 active link
    per source (not duplicated)."""
    cid, doc_id, ver_id = fresh_clause
    _seed_data_element(engine, ver_id, name_zh="字段 A",
                        bound_table=_TEST_TABLE_A)
    try:
        s = SynonymStrategy()
        s.run(version_id=ver_id, by_user="admin")
        s.run(version_id=ver_id, by_user="admin")
        with engine.connect() as c:
            n_active = c.execute(text(
                "SELECT COUNT(*) FROM std_derived_link "
                "WHERE source_version_id=:v AND status='active' "
                "  AND derivation_strategy='to_synonym'"
            ), {"v": ver_id}).scalar()
        assert n_active == 1
        syns = _read_synonyms(engine, semantic_sources[_TEST_TABLE_A])
        # No duplicates from the second run
        assert syns.count("字段 A") == 1
    finally:
        _cleanup(engine, doc_id, semantic_sources.values())


def test_manual_synonyms_untouched(engine, fresh_clause, semantic_sources):
    """The manual `synonyms` column is never overwritten by SynonymStrategy."""
    cid, doc_id, ver_id = fresh_clause
    sid = semantic_sources[_TEST_TABLE_A]
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE agent_semantic_sources "
            "SET synonyms = CAST(:s AS jsonb) WHERE id = :i"
        ), {"s": json.dumps(["手工别名 1", "manual 2"], ensure_ascii=False),
             "i": sid})
    _seed_data_element(engine, ver_id, name_zh="派生别名",
                        bound_table=_TEST_TABLE_A)
    try:
        s = SynonymStrategy()
        s.run(version_id=ver_id, by_user="admin")
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT synonyms, derived_synonyms "
                "FROM agent_semantic_sources WHERE id=:i"
            ), {"i": sid}).first()
        manual = row[0] if isinstance(row[0], list) else json.loads(row[0])
        derived = row[1] if isinstance(row[1], list) else json.loads(row[1])
        assert "手工别名 1" in manual
        assert "manual 2" in manual
        assert "派生别名" not in manual         # manual untouched
        assert "派生别名" in derived             # derived populated
        assert "手工别名 1" not in derived       # derived isolated
    finally:
        _cleanup(engine, doc_id, semantic_sources.values())
