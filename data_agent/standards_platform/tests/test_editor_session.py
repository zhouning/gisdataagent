"""Unit tests for editor_session."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text as _sql

from data_agent.db_engine import get_engine
from data_agent.standards_platform.drafting.editor_session import compute_checksum


@pytest.fixture
def db():
    # Project convention: data_agent/.env holds POSTGRES_* creds.  The
    # Chainlit entrypoint and the outbox_worker both call load_dotenv()
    # explicitly; pytest does not, so we load it here so subsequent
    # std_platform tests (Wave 1 T3-T7) all see the connection settings.
    import os
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__),
                            "..", "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)
    eng = get_engine()
    if eng is None:
        pytest.skip("DB engine unavailable")
    return eng


@pytest.fixture
def clause_row(db):
    """Insert a throwaway document/version/clause and yield (clause_id, vid).
    Clean up at teardown via document CASCADE."""
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    clause_id = str(uuid.uuid4())
    with db.begin() as conn:
        conn.execute(_sql("""
            INSERT INTO std_document (id, doc_code, title, source_type, status,
                                       owner_user_id)
            VALUES (:i, :c, :t, 'draft', 'ingested', 'test')
        """), {"i": doc_id, "c": f"T-EDIT-{doc_id[:6]}", "t": "test-edit"})
        conn.execute(_sql("""
            INSERT INTO std_document_version (id, document_id, version_label,
                                               semver_major, status)
            VALUES (:i, :d, 'v1.0', 1, 'draft')
        """), {"i": ver_id, "d": doc_id})
        conn.execute(_sql("""
            INSERT INTO std_clause (id, document_id, document_version_id,
                                     ordinal_path, clause_no, kind, body_md)
            VALUES (:i, :d, :v, CAST('1' AS ltree), '1', 'clause',
                    'initial body')
        """), {"i": clause_id, "d": doc_id, "v": ver_id})
    yield clause_id, ver_id, doc_id
    with db.begin() as conn:
        conn.execute(_sql("DELETE FROM std_document WHERE id=:d"),
                     {"d": doc_id})


def test_compute_checksum_is_stable():
    assert compute_checksum("hello") == compute_checksum("hello")


def test_compute_checksum_changes_with_content():
    assert compute_checksum("hello") != compute_checksum("hello!")


def test_compute_checksum_returns_16_hex():
    c = compute_checksum("any content")
    assert len(c) == 16
    int(c, 16)  # must be valid hex


def test_clause_fixture_round_trips(db, clause_row):
    cid, _vid, _did = clause_row
    with db.connect() as c:
        row = c.execute(_sql(
            "SELECT body_md FROM std_clause WHERE id=:i"
        ), {"i": cid}).first()
    assert row is not None
    assert row[0] == "initial body"
