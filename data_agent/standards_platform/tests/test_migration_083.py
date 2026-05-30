"""Tests for migration 083 — agent_quality_rules derived columns + FK."""
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


def _constraint_exists(engine, name: str) -> bool:
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conname=:n"
        ), {"n": name}).first()
    return row is not None


def _index_exists(engine, name: str) -> bool:
    with engine.connect() as c:
        row = c.execute(text(
            "SELECT 1 FROM pg_indexes WHERE indexname=:n"
        ), {"n": name}).first()
    return row is not None


def test_083_columns_added(engine):
    """All four derived-tracking columns landed."""
    for col in ("std_derived_link_id", "std_version_id",
                "source_tag", "derived_status"):
        assert _column_exists(engine, "agent_quality_rules", col), (
            f"agent_quality_rules.{col} missing — migration 083 not applied?"
        )


def test_083_fk_to_std_derived_link(engine):
    assert _constraint_exists(engine, "agent_quality_rules_derived_link_fk"), (
        "FK agent_quality_rules.std_derived_link_id -> std_derived_link(id) "
        "missing — migration 083 not applied?"
    )


def test_083_status_check_constraint(engine):
    assert _constraint_exists(engine, "agent_quality_rules_derived_status_check"), (
        "CHECK constraint on agent_quality_rules.derived_status missing"
    )


def test_083_indices(engine):
    assert _index_exists(engine, "idx_agent_quality_rules_derived")
    assert _index_exists(engine, "idx_agent_quality_rules_link")


def test_083_fk_set_null_on_delete(engine):
    """Deleting a std_derived_link sets the FK column NULL, doesn't cascade."""
    import uuid

    # Seed a minimum doc + version for the link's FK.
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) "
            "VALUES (:i, :c, 't083', 'draft', 'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-MIG083-{doc_id[:6]}"})
        conn.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) "
            "VALUES (:i, :d, 'v1', 'draft', 1)"
        ), {"i": ver_id, "d": doc_id})

    link_id = str(uuid.uuid4())
    rule_id = None
    try:
        with engine.begin() as conn:
            # We need a valid source_id (UUID NOT NULL) — reuse ver_id as a
            # throwaway uuid, kind="data_element" CHECK passes, source_id has
            # no FK constraint at this layer.
            conn.execute(text(
                "INSERT INTO std_derived_link "
                "(id, source_kind, source_id, source_version_id, "
                " target_kind, target_table, target_id, "
                " derivation_strategy, status) "
                "VALUES (:i, 'data_element', :s, :v, 'qc_rule', "
                "        'agent_quality_rules', '0', 'to_qc_rule', 'pending')"
            ), {"i": link_id, "s": ver_id, "v": ver_id})

            rid = conn.execute(text(
                "INSERT INTO agent_quality_rules "
                "(rule_name, rule_type, config, owner_username, "
                " std_derived_link_id, derived_status) "
                "VALUES (:n, 'completeness', '{}'::jsonb, 'test_mig083', "
                "        :l, 'active') RETURNING id"
            ), {"n": f"std:test_mig083:{link_id[:8]}", "l": link_id}).scalar()
            rule_id = rid

        # Now delete the link; rule should remain but FK column becomes NULL.
        with engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM std_derived_link WHERE id=:i"
            ), {"i": link_id})
        with engine.connect() as c:
            link_col = c.execute(text(
                "SELECT std_derived_link_id FROM agent_quality_rules "
                "WHERE id=:i"
            ), {"i": rule_id}).scalar()
        assert link_col is None, "FK should SET NULL on link delete"
    finally:
        with engine.begin() as conn:
            if rule_id is not None:
                conn.execute(text(
                    "DELETE FROM agent_quality_rules WHERE id=:i"
                ), {"i": rule_id})
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_083_status_check_rejects_invalid(engine):
    """derived_status must be NULL/active/stale only."""
    with engine.begin() as conn:
        with pytest.raises(Exception):
            conn.execute(text(
                "INSERT INTO agent_quality_rules "
                "(rule_name, rule_type, config, owner_username, "
                " derived_status) "
                "VALUES (:n, 'completeness', '{}'::jsonb, 'test_mig083_bad', "
                "        'bogus')"
            ), {"n": "test_mig083_invalid_status"})
