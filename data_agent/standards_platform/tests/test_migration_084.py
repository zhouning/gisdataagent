"""Tests for migration 084 — agent_defect_code_bindings."""
from __future__ import annotations

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


def test_084_table_exists(engine):
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name='agent_defect_code_bindings'"
        )).first()
    assert row is not None


def test_084_columns(engine):
    expected = {
        "id", "std_data_element_id", "defect_code", "severity",
        "category", "binding_kind", "notes", "std_derived_link_id",
        "std_version_id", "source_tag", "derived_status",
        "owner_username", "created_at", "updated_at",
    }
    with engine.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='agent_defect_code_bindings'"
        )).fetchall()}
    missing = expected - cols
    assert not missing, f"missing columns: {missing}"


def test_084_indices(engine):
    for name in (
        "idx_defect_bindings_element",
        "idx_defect_bindings_code",
        "idx_defect_bindings_link",
        "idx_defect_bindings_derived",
    ):
        assert _index_exists(engine, name), f"missing index {name}"


def test_084_severity_check(engine, fresh_clause):
    """severity must be A/B/C only."""
    import uuid
    cid, doc_id, ver_id = fresh_clause
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation, bound_table, bound_column) "
            "VALUES (:i, :v, 'E', 'n', 'string', 'optional', "
            " 'cq_dltb', 'col')"
        ), {"i": eid, "v": ver_id})

    with engine.begin() as conn:
        with pytest.raises(Exception):
            conn.execute(text(
                "INSERT INTO agent_defect_code_bindings "
                "(std_data_element_id, defect_code, severity, category, "
                " binding_kind) "
                "VALUES (:e, 'TEST', 'X', 'norm_violation', 'manual')"
            ), {"e": eid})


def test_084_unique_kind_code(engine, fresh_clause):
    """UNIQUE (element, defect_code, binding_kind)."""
    import uuid
    cid, doc_id, ver_id = fresh_clause
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation, bound_table, bound_column) "
            "VALUES (:i, :v, 'E', 'n', 'string', 'mandatory', "
            " 'cq_dltb', 'col')"
        ), {"i": eid, "v": ver_id})
        conn.execute(text(
            "INSERT INTO agent_defect_code_bindings "
            "(std_data_element_id, defect_code, severity, category, "
            " binding_kind) "
            "VALUES (:e, 'MIS-001', 'A', 'info_missing', 'mandatory')"
        ), {"e": eid})

    # Same triple → UNIQUE violation.
    with engine.begin() as conn:
        with pytest.raises(Exception):
            conn.execute(text(
                "INSERT INTO agent_defect_code_bindings "
                "(std_data_element_id, defect_code, severity, category, "
                " binding_kind) "
                "VALUES (:e, 'MIS-001', 'A', 'info_missing', 'mandatory')"
            ), {"e": eid})


def test_084_element_cascade_delete(engine, fresh_clause):
    """Deleting a data_element cascades to bindings."""
    import uuid
    cid, doc_id, ver_id = fresh_clause
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation, bound_table, bound_column) "
            "VALUES (:i, :v, 'E', 'n', 'string', 'mandatory', "
            " 'cq_dltb', 'col')"
        ), {"i": eid, "v": ver_id})
        conn.execute(text(
            "INSERT INTO agent_defect_code_bindings "
            "(std_data_element_id, defect_code, severity, category, "
            " binding_kind) "
            "VALUES (:e, 'MIS-001', 'A', 'info_missing', 'mandatory')"
        ), {"e": eid})

    # Delete element → bindings gone.
    with engine.begin() as conn:
        conn.execute(text(
            "DELETE FROM std_data_element WHERE id=:i"
        ), {"i": eid})
    with engine.connect() as c:
        n = c.execute(text(
            "SELECT count(*) FROM agent_defect_code_bindings "
            "WHERE std_data_element_id=:e"
        ), {"e": eid}).scalar()
    assert n == 0
