"""Schema-level checks for migration 078 (std_review_round + std_review_comment)."""
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


def _seed_doc_version(eng):
    """Create throwaway doc + version, return (doc_id, version_id)."""
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-078-{doc_id[:6]}"})
        conn.execute(text(
            "INSERT INTO std_document_version (id, document_id, "
            "version_label, status, semver_major) VALUES (:i, :d, 'v1.0', "
            "'draft', 1)"
        ), {"i": ver_id, "d": doc_id})
    return doc_id, ver_id


def test_review_round_columns_exist():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='std_review_round'"
        )).fetchall()}
    assert {"id", "document_version_id", "reviewer_user_id",
            "initiated_by", "initiated_at", "closed_at",
            "status", "outcome"}.issubset(cols)


def test_review_comment_columns_exist():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='std_review_comment'"
        )).fetchall()}
    assert {"id", "round_id", "clause_id", "parent_comment_id",
            "author_user_id", "body_md", "resolution",
            "created_at", "resolved_at", "resolved_by"}.issubset(cols)


def test_round_status_check_rejects_invalid():
    eng = _get_engine_or_skip()
    doc_id, ver_id = _seed_doc_version(eng)
    try:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_review_round (id, document_version_id, "
                    "reviewer_user_id, initiated_by, status) VALUES "
                    "(:i, :v, 'rev', 'admin', 'bogus')"
                ), {"i": str(uuid.uuid4()), "v": ver_id})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_round_outcome_consistency_check():
    """status=closed without outcome must be rejected."""
    eng = _get_engine_or_skip()
    doc_id, ver_id = _seed_doc_version(eng)
    try:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_review_round (id, document_version_id, "
                    "reviewer_user_id, initiated_by, status, closed_at) "
                    "VALUES (:i, :v, 'rev', 'admin', 'closed', now())"
                ), {"i": str(uuid.uuid4()), "v": ver_id})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_one_open_round_per_version():
    """UNIQUE partial index must reject a 2nd open round on same version."""
    eng = _get_engine_or_skip()
    doc_id, ver_id = _seed_doc_version(eng)
    r1 = str(uuid.uuid4())
    try:
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_review_round (id, document_version_id, "
                "reviewer_user_id, initiated_by) VALUES (:i, :v, 'rev1', 'admin')"
            ), {"i": r1, "v": ver_id})
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_review_round (id, document_version_id, "
                    "reviewer_user_id, initiated_by) VALUES (:i, :v, 'rev2', 'admin')"
                ), {"i": str(uuid.uuid4()), "v": ver_id})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_comment_body_nonempty_check():
    """Whitespace-only body_md must be rejected."""
    eng = _get_engine_or_skip()
    doc_id, ver_id = _seed_doc_version(eng)
    cid = str(uuid.uuid4())
    rid = str(uuid.uuid4())
    try:
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_clause (id, document_id, document_version_id, "
                "ordinal_path, clause_no, kind, body_md) VALUES (:i, :d, :v, "
                "CAST('1' AS ltree), '1', 'clause', 'hello')"
            ), {"i": cid, "d": doc_id, "v": ver_id})
            conn.execute(text(
                "INSERT INTO std_review_round (id, document_version_id, "
                "reviewer_user_id, initiated_by) VALUES (:i, :v, 'rev', 'admin')"
            ), {"i": rid, "v": ver_id})
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_review_comment (id, round_id, clause_id, "
                    "author_user_id, body_md) VALUES (:i, :r, :c, 'rev', '   ')"
                ), {"i": str(uuid.uuid4()), "r": rid, "c": cid})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})
