"""Schema-level checks for migration 076 (std_reference extension)."""
from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from data_agent.db_engine import get_engine


def _get_engine_or_skip():
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)
    eng = get_engine()
    if eng is None:
        pytest.skip("DB engine unavailable")
    return eng


def _seed_clause(eng):
    """Create a throwaway document/version/clause; return (clause_id, ver_id, doc_id)."""
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-076-{doc_id[:6]}"})
        conn.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) VALUES (:i, :d, 'v1.0', "
            "'draft', 1)"
        ), {"i": ver_id, "d": doc_id})
        conn.execute(text(
            "INSERT INTO std_clause (id, document_id, document_version_id, "
            "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
            "CAST('1' AS ltree), '1', 'clause', 'hello')"
        ), {"i": cid, "d": doc_id, "v": ver_id})
    return cid, ver_id, doc_id


def test_new_columns_exist():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='std_reference'"
        )).fetchall()}
    assert {"target_data_element_id", "target_term_id",
            "inserted_by", "inserted_at",
            "verification_status"}.issubset(cols)


def test_target_kind_check_accepts_new_values():
    eng = _get_engine_or_skip()
    cid, ver_id, doc_id = _seed_clause(eng)
    de_id = str(uuid.uuid4())
    ref_id = str(uuid.uuid4())
    try:
        with eng.begin() as conn:
            # Need a real data_element to satisfy the FK; use ver_id directly
            conn.execute(text(
                "INSERT INTO std_data_element (id, document_version_id, "
                "name_zh, code) VALUES (:i, :v, '测试要素', :c)"
            ), {"i": de_id, "v": ver_id, "c": "TEST_DE_076"})
            conn.execute(text(
                "INSERT INTO std_reference (id, source_clause_id, target_kind, "
                "target_data_element_id, citation_text) "
                "VALUES (:i, :s, 'std_data_element', :t, 'cite')"
            ), {"i": ref_id, "s": cid, "t": de_id})
        # Assert the row was inserted with correct values
        with eng.connect() as conn:
            row = conn.execute(text(
                "SELECT target_kind, target_data_element_id "
                "FROM std_reference WHERE id=:i"
            ), {"i": ref_id}).first()
        assert row is not None
        assert row[0] == "std_data_element"
        assert str(row[1]) == de_id
    finally:
        # CASCADE: deleting std_document removes version → clause → reference
        # and version → data_element automatically
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"), {"i": doc_id})


def test_target_consistency_rejects_mismatch():
    """target_kind=std_clause but target_clause_id NULL must be rejected."""
    eng = _get_engine_or_skip()
    cid, ver_id, doc_id = _seed_clause(eng)
    try:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_reference (id, source_clause_id, "
                    "target_kind, target_clause_id, citation_text) "
                    "VALUES (:i, :s, 'std_clause', NULL, 'bad')"
                ), {"i": str(uuid.uuid4()), "s": cid})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"), {"i": doc_id})


def test_verification_status_defaults_pending():
    eng = _get_engine_or_skip()
    cid, ver_id, doc_id = _seed_clause(eng)
    ref_id = str(uuid.uuid4())
    try:
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_reference (id, source_clause_id, target_kind, "
                "target_clause_id, citation_text) "
                "VALUES (:i, :s, 'std_clause', :s, 'cite')"
            ), {"i": ref_id, "s": cid})
        with eng.connect() as conn:
            row = conn.execute(text(
                "SELECT verification_status FROM std_reference WHERE id=:i"
            ), {"i": ref_id}).first()
        assert row[0] == "pending"
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"), {"i": doc_id})


def test_verification_status_check_rejects_invalid():
    eng = _get_engine_or_skip()
    cid, ver_id, doc_id = _seed_clause(eng)
    try:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_reference (id, source_clause_id, "
                    "target_kind, target_clause_id, citation_text, "
                    "verification_status) "
                    "VALUES (:i, :s, 'std_clause', :s, 'c', 'bogus')"
                ), {"i": str(uuid.uuid4()), "s": cid})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"), {"i": doc_id})


def test_external_url_target_requires_url():
    eng = _get_engine_or_skip()
    cid, ver_id, doc_id = _seed_clause(eng)
    try:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_reference (id, source_clause_id, "
                    "target_kind, target_url, citation_text) "
                    "VALUES (:i, :s, 'external_url', NULL, 'c')"
                ), {"i": str(uuid.uuid4()), "s": cid})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"), {"i": doc_id})
