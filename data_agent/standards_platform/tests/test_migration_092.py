"""Integration checks for migration 092 standard application contracts."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _columns(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name=:table"
        ), {"table": table}).fetchall()}


def test_092_contract_tables_have_version_and_evidence_columns(engine):
    assert {
        "id", "source_kind", "source_ref", "source_snapshot_hash",
        "standard_version_id", "status", "mapping_hash", "created_by",
        "confirmed_by", "confirmed_at", "superseded_at", "metadata",
    } <= _columns(engine, "std_application_mapping_contract")
    assert {
        "contract_id", "standard_version_id", "source_field",
        "target_data_element_id", "target_field", "confidence",
        "match_method", "evidence", "transform_spec",
    } <= _columns(engine, "std_application_field_mapping")


def test_092_rejects_data_element_from_another_standard_version(engine, fresh_clause):
    _, doc_id, version_id = fresh_clause
    other_version_id = str(uuid.uuid4())
    target_id = str(uuid.uuid4())
    contract_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_document_version (
                id, document_id, version_label, status, semver_major)
            VALUES (:id, :doc, 'v2.0', 'released', 2)
        """), {"id": other_version_id, "doc": doc_id})
        conn.execute(text("""
            INSERT INTO std_data_element (
                id, document_version_id, code, name_zh)
            VALUES (:id, :version_id, 'OTHER', '其他字段')
        """), {"id": target_id, "version_id": other_version_id})
        conn.execute(text("""
            INSERT INTO std_application_mapping_contract (
                id, source_kind, source_ref, standard_version_id, status,
                mapping_hash, created_by)
            VALUES (:id, 'virtual_source', '7', :version_id, 'proposed',
                    :mapping_hash, 'alice')
        """), {
            "id": contract_id,
            "version_id": version_id,
            "mapping_hash": "b" * 64,
        })

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO std_application_field_mapping (
                    contract_id, standard_version_id, source_field,
                    target_data_element_id, target_field, confidence,
                    match_method)
                VALUES (:contract_id, :version_id, 'src', :target_id,
                        'OTHER', 1, 'human_confirmed')
            """), {
                "contract_id": contract_id,
                "version_id": version_id,
                "target_id": target_id,
            })
