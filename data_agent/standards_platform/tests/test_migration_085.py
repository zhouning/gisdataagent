"""Tests for migration 085 — std_data_model_snapshot + std_derived_link
CHECK widening."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text


def _column_exists(engine, table: str, column: str) -> bool:
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name=:t AND column_name=:c"
        ), {"t": table, "c": column}).first()
    return row is not None


def _index_exists(engine, name: str) -> bool:
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT 1 FROM pg_indexes WHERE indexname=:n"
        ), {"n": name}).first()
    return row is not None


def test_085_table_exists(engine):
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name='std_data_model_snapshot'"
        )).first()
    assert row is not None


def test_085_columns(engine):
    expected = {
        "id", "document_version_id", "generated_at", "generated_by",
        "cdm_json", "ldm_json", "pdm_json", "ddl_postgresql",
        "entity_count", "attribute_count", "constraint_count",
        "std_derived_link_id", "derived_status", "source_tag",
        "updated_at",
    }
    with engine.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='std_data_model_snapshot'"
        )).fetchall()}
    missing = expected - cols
    assert not missing, f"missing columns: {missing}"


def test_085_indices(engine):
    for name in (
        "idx_std_dm_snapshot_version",
        "idx_std_dm_snapshot_active",
        "idx_std_dm_snapshot_link",
    ):
        assert _index_exists(engine, name), f"missing index {name}"


def test_085_derived_status_check(engine, fresh_clause):
    _, _, ver_id = fresh_clause
    with engine.begin() as conn:
        with pytest.raises(Exception):
            conn.execute(text(
                "INSERT INTO std_data_model_snapshot "
                "(document_version_id, derived_status) "
                "VALUES (:v, 'bogus')"
            ), {"v": ver_id})


def test_085_version_cascade_delete(engine, fresh_clause):
    """Deleting the document cascades through version → snapshot."""
    _, doc_id, ver_id = fresh_clause
    sid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_model_snapshot "
            "(id, document_version_id) VALUES (:i, :v)"
        ), {"i": sid, "v": ver_id})

    # Sanity: row inserted.
    with engine.connect() as c:
        n = c.execute(text(
            "SELECT count(*) FROM std_data_model_snapshot WHERE id=:i"
        ), {"i": sid}).scalar()
    assert n == 1

    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM std_document WHERE id=:i"
        ), {"i": doc_id})
    with engine.connect() as c:
        n = c.execute(text(
            "SELECT count(*) FROM std_data_model_snapshot WHERE id=:i"
        ), {"i": sid}).scalar()
    assert n == 0


def test_085_widened_source_kind_admits_document_version(engine, fresh_clause):
    """source_kind='document_version' must be accepted post-085."""
    _, _, ver_id = fresh_clause
    sid = str(uuid.uuid4())
    lid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_model_snapshot (id, document_version_id) "
            "VALUES (:i, :v)"
        ), {"i": sid, "v": ver_id})
        conn.execute(text(
            "INSERT INTO std_derived_link "
            "(id, source_kind, source_id, source_version_id, "
            " target_kind, target_table, target_id, "
            " derivation_strategy, status) "
            "VALUES (:i, 'document_version', :s, :v, "
            " 'data_model', 'std_data_model_snapshot', :t, "
            " 'to_data_model', 'active')"
        ), {"i": lid, "s": ver_id, "v": ver_id, "t": sid})

    with engine.connect() as c:
        n = c.execute(text(
            "SELECT count(*) FROM std_derived_link WHERE id=:i"
        ), {"i": lid}).scalar()
    assert n == 1


def test_085_widened_kind_still_rejects_garbage(engine, fresh_clause):
    """Widening must not accept arbitrary values — both source/target_kind
    are still constrained to the documented set."""
    _, _, ver_id = fresh_clause
    with engine.begin() as conn:
        with pytest.raises(Exception):
            conn.execute(text(
                "INSERT INTO std_derived_link "
                "(source_kind, source_id, source_version_id, "
                " target_kind, target_table, target_id, "
                " derivation_strategy) "
                "VALUES ('not_a_real_kind', :s, :v, 'data_model', "
                " 'std_data_model_snapshot', 'tid', 'to_data_model')"
            ), {"s": ver_id, "v": ver_id})

    with engine.begin() as conn:
        with pytest.raises(Exception):
            conn.execute(text(
                "INSERT INTO std_derived_link "
                "(source_kind, source_id, source_version_id, "
                " target_kind, target_table, target_id, "
                " derivation_strategy) "
                "VALUES ('document_version', :s, :v, 'not_a_real_target', "
                " 'std_data_model_snapshot', 'tid', 'to_data_model')"
            ), {"s": ver_id, "v": ver_id})


def test_085_pre_existing_target_kinds_still_admitted(engine, fresh_clause):
    """Wave 7 strategies write target_kind='qc_rule' etc. — make sure the
    widened CHECK is a strict superset, not a replacement."""
    _, _, ver_id = fresh_clause
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation, bound_table, bound_column) "
            "VALUES (:i, :v, 'E', 'n', 'string', 'mandatory', "
            " 'cq_dltb', 'col')"
        ), {"i": eid, "v": ver_id})
        # Pre-085 kinds must continue to insert cleanly.
        for tk in ('semantic_hint', 'qc_rule', 'defect_code', 'synonym',
                   'value_semantic'):
            conn.execute(text(
                "INSERT INTO std_derived_link "
                "(source_kind, source_id, source_version_id, "
                " target_kind, target_table, target_id, "
                " derivation_strategy) "
                "VALUES ('data_element', :s, :v, :tk, 'tbl', "
                " :tid, 'test')"
            ), {"s": eid, "v": ver_id, "tk": tk, "tid": str(uuid.uuid4())})
