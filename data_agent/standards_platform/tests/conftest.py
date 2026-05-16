"""Shared fixtures for standards_platform API tests.

Replaces the duplicated _get_engine_or_skip / _seed_clause helpers that
previously lived in test_api_drafting.py and test_api_citation.py.
"""
from __future__ import annotations

import os
import uuid

import pytest
from dotenv import load_dotenv
from sqlalchemy import text

from data_agent.db_engine import get_engine


@pytest.fixture
def engine():
    """Engine or pytest.skip if DB unavailable."""
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)
    eng = get_engine()
    if eng is None:
        pytest.skip("DB engine unavailable")
    return eng


@pytest.fixture
def fresh_clause(engine):
    """Insert a throwaway document/version/clause and return (clause_id, doc_id, version_id).

    Note: returns three values now (vs. two in the old _seed_clause). Tests
    that only need clause_id/doc_id can unpack with `cid, did, _ = fresh_clause`.
    Returning version_id makes Task 4's data_element/term seeding straightforward.
    """
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-CONFTEST-{doc_id[:6]}"})
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
    return cid, doc_id, ver_id
