"""Tests for DefectTaxonomyStrategy (Wave 7 — to_defect_code)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.derivation.strategies.defect_taxonomy import (
    DefectTaxonomyStrategy,
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


def _collect(engine, version_id):
    with engine.connect() as c:
        bind_ids = [str(r[0]) for r in c.execute(text(
            "SELECT id FROM agent_defect_code_bindings WHERE std_version_id=:v"
        ), {"v": version_id}).fetchall()]
        link_ids = [str(r[0]) for r in c.execute(text(
            "SELECT id FROM std_derived_link "
            "WHERE source_version_id=:v AND derivation_strategy='to_defect_code'"
        ), {"v": version_id}).fetchall()]
    return bind_ids, link_ids


def _cleanup(engine, doc_id, *, bind_ids=None, link_ids=None):
    with engine.begin() as conn:
        if bind_ids:
            conn.execute(text(
                "DELETE FROM agent_defect_code_bindings "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"ids": bind_ids})
        if link_ids:
            conn.execute(text(
                "DELETE FROM std_derived_link "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"ids": link_ids})
        conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                     {"i": doc_id})


def test_mandatory_emits_mis_001(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, obligation="mandatory")
    s = DefectTaxonomyStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    bind_ids, link_ids = _collect(engine, ver_id)
    try:
        assert len(result.new_links) == 1
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT defect_code, severity, category, binding_kind, "
                "       derived_status "
                "FROM agent_defect_code_bindings WHERE id=:i"
            ), {"i": bind_ids[0]}).first()
        assert row[0] == "MIS-001"
        assert row[1] == "A"  # severity from YAML
        assert row[2] == "info_missing"
        assert row[3] == "mandatory"
        assert row[4] == "active"
    finally:
        _cleanup(engine, doc_id, bind_ids=bind_ids, link_ids=link_ids)


def test_enumeration_emits_nrm_003(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    vd_id = _seed_value_domain(
        engine, ver_id, kind="enumeration",
        items=[("0101", "水田")],
    )
    _seed_element(engine, ver_id, obligation="optional",
                  value_domain_id=vd_id)
    s = DefectTaxonomyStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    bind_ids, link_ids = _collect(engine, ver_id)
    try:
        assert len(result.new_links) == 1
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT defect_code, severity, binding_kind "
                "FROM agent_defect_code_bindings WHERE id=:i"
            ), {"i": bind_ids[0]}).first()
        assert row[0] == "NRM-003"
        assert row[1] == "B"
        assert row[2] == "enumeration"
    finally:
        _cleanup(engine, doc_id, bind_ids=bind_ids, link_ids=link_ids)


def test_pattern_emits_nrm_002(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    vd_id = _seed_value_domain(
        engine, ver_id, kind="pattern",
        items=[(r"^\d{4}$", "四位")],
    )
    _seed_element(engine, ver_id, obligation="optional",
                  value_domain_id=vd_id)
    s = DefectTaxonomyStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    bind_ids, link_ids = _collect(engine, ver_id)
    try:
        assert len(result.new_links) == 1
        with engine.connect() as c:
            code, sev = c.execute(text(
                "SELECT defect_code, severity FROM agent_defect_code_bindings "
                "WHERE id=:i"
            ), {"i": bind_ids[0]}).first()
        assert code == "NRM-002"
        assert sev == "C"
    finally:
        _cleanup(engine, doc_id, bind_ids=bind_ids, link_ids=link_ids)


def test_mandatory_with_enum_two_bindings(engine, fresh_clause):
    """Mandatory + enum → MIS-001 + NRM-003 both bound."""
    cid, doc_id, ver_id = fresh_clause
    vd_id = _seed_value_domain(
        engine, ver_id, kind="enumeration",
        items=[("0101", "水田")],
    )
    _seed_element(engine, ver_id, obligation="mandatory",
                  value_domain_id=vd_id)
    s = DefectTaxonomyStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    bind_ids, link_ids = _collect(engine, ver_id)
    try:
        assert len(result.new_links) == 2
        with engine.connect() as c:
            codes = {r[0] for r in c.execute(text(
                "SELECT defect_code FROM agent_defect_code_bindings "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"ids": bind_ids}).fetchall()}
        assert codes == {"MIS-001", "NRM-003"}
    finally:
        _cleanup(engine, doc_id, bind_ids=bind_ids, link_ids=link_ids)


def test_optional_no_domain_skipped(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, obligation="optional",
                  value_domain_id=None)
    s = DefectTaxonomyStrategy()
    result = s.run(version_id=ver_id, by_user="admin")
    bind_ids, link_ids = _collect(engine, ver_id)
    try:
        assert len(result.new_links) == 0
        assert bind_ids == []
    finally:
        _cleanup(engine, doc_id, bind_ids=bind_ids, link_ids=link_ids)


def test_rerun_idempotent(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, obligation="mandatory")
    s = DefectTaxonomyStrategy()
    s.run(version_id=ver_id, by_user="admin")
    s.run(version_id=ver_id, by_user="admin")
    bind_ids, link_ids = _collect(engine, ver_id)
    try:
        assert len(bind_ids) == 1
        with engine.connect() as c:
            n_active = c.execute(text(
                "SELECT count(*) FROM std_derived_link "
                "WHERE source_version_id=:v "
                "  AND derivation_strategy='to_defect_code' "
                "  AND status='active'"
            ), {"v": ver_id}).scalar()
        assert n_active == 1
    finally:
        _cleanup(engine, doc_id, bind_ids=bind_ids, link_ids=link_ids)


def test_supersede_marks_stale(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, obligation="mandatory")
    s = DefectTaxonomyStrategy()
    s.run(version_id=ver_id, by_user="admin")

    # v2 — same document, no elements at all.
    ver2_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) "
            "VALUES (:i, :d, 'v2.0', 'draft', 2)"
        ), {"i": ver2_id, "d": doc_id})
    s.run(version_id=ver2_id, by_user="admin")

    bind_ids, link_ids = _collect(engine, ver_id)
    try:
        with engine.connect() as c:
            status = c.execute(text(
                "SELECT derived_status FROM agent_defect_code_bindings "
                "WHERE id=:i"
            ), {"i": bind_ids[0]}).scalar()
        assert status == "stale"
    finally:
        _cleanup(engine, doc_id, bind_ids=bind_ids, link_ids=link_ids)
