"""Schema-level checks for migration 077 (relax internet_search url requirement)."""
from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text

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
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-077-{doc_id[:6]}"})
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
    return cid, doc_id


def test_internet_search_with_null_url_accepted():
    """Migration 077: internet_search row with target_url=NULL must be accepted."""
    eng = _get_engine_or_skip()
    cid, doc_id = _seed_clause(eng)
    ref_id = str(uuid.uuid4())
    try:
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_reference (id, source_clause_id, "
                "target_kind, target_url, citation_text) "
                "VALUES (:i, :s, 'internet_search', NULL, 'kb cite')"
            ), {"i": ref_id, "s": cid})
        with eng.connect() as conn:
            row = conn.execute(text(
                "SELECT target_kind, target_url FROM std_reference WHERE id=:i"
            ), {"i": ref_id}).first()
        assert row[0] == "internet_search"
        assert row[1] is None
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_external_url_still_requires_url():
    """external_url must still require non-NULL target_url."""
    from sqlalchemy.exc import IntegrityError

    eng = _get_engine_or_skip()
    cid, doc_id = _seed_clause(eng)
    try:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_reference (id, source_clause_id, "
                    "target_kind, target_url, citation_text) "
                    "VALUES (:i, :s, 'external_url', NULL, 'bad')"
                ), {"i": str(uuid.uuid4()), "s": cid})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})
