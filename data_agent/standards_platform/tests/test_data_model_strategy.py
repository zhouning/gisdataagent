"""Tests for DataModelStrategy (Wave 8 — to_data_model).

Pattern follows test_qc_rule_strategy.py: seed std_data_element + value_domain
under fresh_clause's version_id, run the strategy, assert against the
snapshot row + std_derived_link row, then clean up.
"""
from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.derivation.strategies.data_model import (
    DataModelStrategy,
)
from data_agent.standards_platform.derivation import link_repo


# ---------------------------------------------------------------- helpers


def _seed_value_domain(engine, ver_id, *, kind="enumeration",
                       code="DLBM_ENUM", name="地类编码",
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
                ), {"i": str(uuid.uuid4()), "v": vid, "val": val,
                     "lbl": lbl, "o": ordinal})
    return vid


def _seed_element(engine, ver_id, *, name_zh="地类编码",
                  bound_table="cq_dltb", bound_column="DLBM",
                  obligation="optional", repr_class="code",
                  unit=None, value_domain_id=None,
                  term_id=None) -> str:
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, representation_class, datatype, unit, obligation, "
            "bound_table, bound_column, value_domain_id, term_id) "
            "VALUES (:i, :v, :c, :n, :rc, 'string', :u, :ob, :bt, :bc, "
            "        :vd, :tid)"
        ), {"i": eid, "v": ver_id, "c": f"E-{eid[:6]}", "n": name_zh,
             "rc": repr_class, "u": unit, "ob": obligation,
             "bt": bound_table, "bc": bound_column,
             "vd": value_domain_id, "tid": term_id})
    return eid


def _collect(engine, version_id):
    with engine.connect() as c:
        snap_ids = [str(r[0]) for r in c.execute(text(
            "SELECT id FROM std_data_model_snapshot "
            "WHERE document_version_id=:v"
        ), {"v": version_id}).fetchall()]
        link_ids = [str(r[0]) for r in c.execute(text(
            "SELECT id FROM std_derived_link "
            "WHERE source_version_id=:v "
            "  AND derivation_strategy='to_data_model'"
        ), {"v": version_id}).fetchall()]
    return snap_ids, link_ids


def _cleanup(engine, doc_id, *, snap_ids=None, link_ids=None):
    with engine.begin() as conn:
        if snap_ids:
            conn.execute(text(
                "DELETE FROM std_data_model_snapshot "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"ids": snap_ids})
        if link_ids:
            conn.execute(text(
                "DELETE FROM std_derived_link "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"ids": link_ids})
        conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                     {"i": doc_id})


# ---------------------------------------------------------------- core tests


def test_single_table_creates_one_snapshot_one_link(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, obligation="mandatory")
    try:
        result = DataModelStrategy().run(version_id=ver_id, by_user="bob")
        assert len(result.new_links) == 1
        assert result.failed == []

        snap_ids, link_ids = _collect(engine, ver_id)
        assert len(snap_ids) == 1
        assert len(link_ids) == 1

        with engine.connect() as c:
            row = c.execute(text(
                "SELECT entity_count, attribute_count, "
                "       derived_status, generated_by, "
                "       (cdm_json->>'layer'), "
                "       (pdm_json->>'layer'), "
                "       ddl_postgresql "
                "FROM std_data_model_snapshot WHERE id=:i"
            ), {"i": snap_ids[0]}).first()
        assert row[0] == 1
        assert row[1] == 1
        assert row[2] == "active"
        assert row[3] == "bob"
        assert row[4] == "CDM"
        assert row[5] == "PDM"
        assert "CREATE TABLE" in row[6]
    finally:
        _cleanup(engine, doc_id)


def test_multi_table_groups_correctly(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, bound_table="cq_a", bound_column="c1")
    _seed_element(engine, ver_id, bound_table="cq_a", bound_column="c2")
    _seed_element(engine, ver_id, bound_table="cq_b", bound_column="c1")
    try:
        DataModelStrategy().run(version_id=ver_id)
        snap_ids, _ = _collect(engine, ver_id)
        with engine.connect() as c:
            entity_count, attr_count = c.execute(text(
                "SELECT entity_count, attribute_count "
                "FROM std_data_model_snapshot WHERE id=:i"
            ), {"i": snap_ids[0]}).first()
        assert entity_count == 2
        assert attr_count == 3
    finally:
        _cleanup(engine, doc_id)


def test_enumeration_value_domain_emits_check(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    vid = _seed_value_domain(engine, ver_id, kind="enumeration",
                              items=[("01", "水田"), ("02", "旱地")])
    _seed_element(engine, ver_id, value_domain_id=vid)
    try:
        DataModelStrategy().run(version_id=ver_id)
        snap_ids, _ = _collect(engine, ver_id)
        with engine.connect() as c:
            ddl = c.execute(text(
                "SELECT ddl_postgresql FROM std_data_model_snapshot "
                "WHERE id=:i"
            ), {"i": snap_ids[0]}).scalar()
        assert "CHECK" in ddl
        assert "'01'" in ddl and "'02'" in ddl
    finally:
        _cleanup(engine, doc_id)


def test_geometry_element_emits_postgis_type_and_gist(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, repr_class="geometry",
                  bound_column="geometry", unit="POLYGON@4490")
    try:
        DataModelStrategy().run(version_id=ver_id)
        snap_ids, _ = _collect(engine, ver_id)
        with engine.connect() as c:
            ddl = c.execute(text(
                "SELECT ddl_postgresql FROM std_data_model_snapshot "
                "WHERE id=:i"
            ), {"i": snap_ids[0]}).scalar()
        assert "GEOMETRY(POLYGON, 4490)" in ddl
        assert "USING GIST" in ddl
    finally:
        _cleanup(engine, doc_id)


def test_mandatory_emits_not_null(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, obligation="mandatory",
                  bound_column="dlbm")
    try:
        DataModelStrategy().run(version_id=ver_id)
        snap_ids, _ = _collect(engine, ver_id)
        with engine.connect() as c:
            ddl = c.execute(text(
                "SELECT ddl_postgresql FROM std_data_model_snapshot "
                "WHERE id=:i"
            ), {"i": snap_ids[0]}).scalar()
        assert "NOT NULL" in ddl
    finally:
        _cleanup(engine, doc_id)


def test_re_derive_marks_prior_stale(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id, bound_column="c1")
    try:
        DataModelStrategy().run(version_id=ver_id)
        DataModelStrategy().run(version_id=ver_id)

        snap_ids, link_ids = _collect(engine, ver_id)
        assert len(snap_ids) == 2  # both preserved (immutable history)
        assert len(link_ids) == 2

        with engine.connect() as c:
            statuses = [r[0] for r in c.execute(text(
                "SELECT derived_status FROM std_data_model_snapshot "
                "WHERE document_version_id=:v ORDER BY generated_at"
            ), {"v": ver_id}).fetchall()]
            link_statuses = [r[0] for r in c.execute(text(
                "SELECT status FROM std_derived_link "
                "WHERE source_version_id=:v "
                "  AND derivation_strategy='to_data_model' "
                "ORDER BY generated_at"
            ), {"v": ver_id}).fetchall()]

        # Old snapshot stale, new active. Old link stale, new active.
        assert statuses == ["stale", "active"]
        assert link_statuses == ["stale", "active"]
    finally:
        _cleanup(engine, doc_id)


def test_manual_snapshot_rows_not_touched(engine, fresh_clause):
    """A snapshot whose derived_status='manual' must survive re-derive."""
    _, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id)
    manual_snap_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_data_model_snapshot "
                "(id, document_version_id, ddl_postgresql, derived_status) "
                "VALUES (:i, :v, '-- manual', 'manual')"
            ), {"i": manual_snap_id, "v": ver_id})

        DataModelStrategy().run(version_id=ver_id)

        with engine.connect() as c:
            status = c.execute(text(
                "SELECT derived_status FROM std_data_model_snapshot "
                "WHERE id=:i"
            ), {"i": manual_snap_id}).scalar()
        assert status == "manual"
    finally:
        _cleanup(engine, doc_id)


def test_unbound_elements_skipped_silently(engine, fresh_clause):
    """std_data_element without bound_table/column don't produce attrs but
    don't fail the run either."""
    _, doc_id, ver_id = fresh_clause
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, representation_class, datatype, obligation) "
            "VALUES (:i, :v, 'E', 'unbound', 'text', 'string', 'optional')"
        ), {"i": eid, "v": ver_id})
    try:
        result = DataModelStrategy().run(version_id=ver_id)
        snap_ids, _ = _collect(engine, ver_id)
        assert len(snap_ids) == 1
        with engine.connect() as c:
            entity_count = c.execute(text(
                "SELECT entity_count FROM std_data_model_snapshot "
                "WHERE id=:i"
            ), {"i": snap_ids[0]}).scalar()
        assert entity_count == 0
        assert result.failed == []
    finally:
        _cleanup(engine, doc_id)


def test_link_uses_document_version_source_kind(engine, fresh_clause):
    _, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id)
    try:
        DataModelStrategy().run(version_id=ver_id)
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT source_kind, source_id, target_kind, target_table "
                "FROM std_derived_link "
                "WHERE source_version_id=:v "
                "  AND derivation_strategy='to_data_model'"
            ), {"v": ver_id}).first()
        assert row[0] == "document_version"
        assert str(row[1]) == ver_id
        assert row[2] == "data_model"
        assert row[3] == "std_data_model_snapshot"
    finally:
        _cleanup(engine, doc_id)


def test_rollback_marks_links_superseded(engine, fresh_clause):
    """Verify Wave 7's link_repo.rollback_version() works on Wave 8 links."""
    _, doc_id, ver_id = fresh_clause
    _seed_element(engine, ver_id)
    try:
        DataModelStrategy().run(version_id=ver_id)
        summary = link_repo.rollback_version(version_id=ver_id, by_user="alice")
        assert "to_data_model" in summary
        assert summary["to_data_model"]["links_marked"] >= 1

        with engine.connect() as c:
            link_status = c.execute(text(
                "SELECT status FROM std_derived_link "
                "WHERE source_version_id=:v "
                "  AND derivation_strategy='to_data_model'"
            ), {"v": ver_id}).scalar()
            snap_status = c.execute(text(
                "SELECT derived_status FROM std_data_model_snapshot "
                "WHERE document_version_id=:v"
            ), {"v": ver_id}).scalar()
        assert link_status == "superseded"
        # rollback should also flip the snapshot to stale.
        assert snap_status == "stale"
    finally:
        _cleanup(engine, doc_id)


def test_runner_lists_to_data_model_as_active():
    """After Wave 8 to_data_model is no longer 'coming_soon'."""
    from data_agent.standards_platform.derivation.runner import (
        get_strategy_status,
    )
    statuses = {s["name"]: s["status"] for s in get_strategy_status()}
    assert statuses["to_data_model"] == "active"
