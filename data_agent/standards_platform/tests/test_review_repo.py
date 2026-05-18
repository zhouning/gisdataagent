"""Unit tests for review/{round_repo,comment_repo,gating}."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.review import (
    round_repo, comment_repo, gating,
)


def test_create_round_flips_version_to_review(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT status FROM std_document_version WHERE id=:v"
            ), {"v": ver_id}).first()
        assert row[0] == "review"
        r = round_repo.get_round(rid)
        assert r["status"] == "open"
        assert r["reviewer_user_id"] == "rev1"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_round_approved_flips_version_to_approved(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        out = round_repo.close_round(round_id=rid, outcome="approved")
        assert out["version_status"] == "approved"
        with engine.connect() as conn:
            v = conn.execute(text(
                "SELECT status FROM std_document_version WHERE id=:v"
            ), {"v": ver_id}).first()[0]
            r = conn.execute(text(
                "SELECT status, outcome FROM std_review_round WHERE id=:i"
            ), {"i": rid}).first()
        assert v == "approved"
        assert r[0] == "closed" and r[1] == "approved"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_round_rejected_flips_version_to_draft(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        out = round_repo.close_round(round_id=rid, outcome="rejected")
        assert out["version_status"] == "draft"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_close_already_closed_round_raises(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        round_repo.close_round(round_id=rid, outcome="approved")
        with pytest.raises(ValueError, match="already closed"):
            round_repo.close_round(round_id=rid, outcome="approved")
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_create_comment_with_parent(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        c1 = comment_repo.create_comment(
            round_id=rid, clause_id=cid,
            author_user_id="rev1", body_md="hello")
        c2 = comment_repo.create_comment(
            round_id=rid, clause_id=cid,
            author_user_id="rev1", body_md="reply",
            parent_comment_id=c1)
        comments = comment_repo.list_comments(round_id=rid, clause_id=cid)
        assert len(comments) == 2
        assert any(c["parent_comment_id"] and str(c["parent_comment_id"]) == c1
                   for c in comments)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_resolve_comment_sets_resolved_metadata(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        comm_id = comment_repo.create_comment(
            round_id=rid, clause_id=cid,
            author_user_id="rev1", body_md="please fix")
        comment_repo.resolve_comment(
            comment_id=comm_id, resolution="accepted",
            resolver_user_id="rev1")
        c = comment_repo.get_comment(comm_id)
        assert c["resolution"] == "accepted"
        assert c["resolved_by"] == "rev1"
        assert c["resolved_at"] is not None
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_gating_open_comment_blocks(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    try:
        comment_repo.create_comment(
            round_id=rid, clause_id=cid,
            author_user_id="rev1", body_md="todo")
        g = gating.check_close_gating(round_id=rid, version_id=ver_id)
        assert g["open_comments"] >= 1
        assert g["blocking"] is True
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})


def test_gating_pending_ref_blocks(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="rev1",
        initiated_by="admin")
    ref_id = str(uuid.uuid4())
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_reference (id, source_clause_id, target_kind, "
                "target_clause_id, citation_text) VALUES "
                "(:i, :s, 'std_clause', :s, 'cite')"
            ), {"i": ref_id, "s": cid})
        g = gating.check_close_gating(round_id=rid, version_id=ver_id)
        assert g["pending_refs"] >= 1
        assert g["blocking"] is True
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_review_round WHERE id=:i"),
                         {"i": rid})
