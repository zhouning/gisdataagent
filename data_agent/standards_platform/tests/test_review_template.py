"""Repository tests for the default review-template visualization."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.review import (
    comment_repo,
    round_repo,
    template_repo,
)


def _step_statuses(template: dict) -> dict[str, str]:
    return {step["id"]: step["status"] for step in template["steps"]}


def _insert_reference(engine, clause_id: str,
                      verification_status: str = "pending") -> str:
    ref_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_reference
                (id, source_clause_id, target_kind, target_clause_id,
                 citation_text, verification_status)
            VALUES
                (:i, :c, 'std_clause', :c, 'cite', :s)
        """), {"i": ref_id, "c": clause_id, "s": verification_status})
    return ref_id


def test_template_for_draft_version_marks_draft_active(fresh_clause):
    cid, doc_id, ver_id = fresh_clause

    template = template_repo.default_review_template(ver_id)

    assert template["template_id"] == "default_review_v1"
    assert template["version_id"] == ver_id
    assert template["version_status"] == "draft"
    statuses = _step_statuses(template)
    assert statuses["draft"] == "active"
    assert statuses["start_review"] == "pending"
    assert statuses["audit_references"] == "pending"
    assert template["summary"]["open_round_id"] is None
    assert template["summary"]["pending_refs"] == 0
    assert template["summary"]["blocking"] is False


def test_template_missing_version_raises_lookup_error():
    with pytest.raises(LookupError, match="version not found"):
        template_repo.default_review_template(str(uuid.uuid4()))


def test_template_blocks_on_pending_references(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="reviewer",
        initiated_by="admin",
    )
    _insert_reference(engine, cid, "pending")
    _insert_reference(engine, cid, "approved")

    template = template_repo.default_review_template(ver_id)

    statuses = _step_statuses(template)
    assert statuses["draft"] == "done"
    assert statuses["start_review"] == "done"
    assert statuses["audit_references"] == "blocked"
    assert statuses["resolve_comments"] == "pending"
    assert template["summary"]["open_round_id"] == rid
    assert template["summary"]["pending_refs"] == 1
    assert template["summary"]["approved_refs"] == 1
    assert template["summary"]["blocking"] is True


def test_template_blocks_on_open_comments(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="reviewer",
        initiated_by="admin",
    )
    _insert_reference(engine, cid, "approved")
    comment_repo.create_comment(
        round_id=rid,
        clause_id=cid,
        author_user_id="reviewer",
        body_md="needs update",
    )

    template = template_repo.default_review_template(ver_id)

    statuses = _step_statuses(template)
    assert statuses["audit_references"] == "done"
    assert statuses["resolve_comments"] == "blocked"
    assert statuses["close_round"] == "pending"
    assert template["summary"]["pending_refs"] == 0
    assert template["summary"]["open_comments"] == 1
    assert template["summary"]["blocking"] is True


def test_template_marks_close_round_active_when_gates_clear(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="reviewer",
        initiated_by="admin",
    )
    _insert_reference(engine, cid, "approved")
    comment_id = comment_repo.create_comment(
        round_id=rid,
        clause_id=cid,
        author_user_id="reviewer",
        body_md="resolved",
    )
    comment_repo.resolve_comment(
        comment_id=comment_id,
        resolution="accepted",
        resolver_user_id="reviewer",
    )

    template = template_repo.default_review_template(ver_id)

    statuses = _step_statuses(template)
    assert statuses["audit_references"] == "done"
    assert statuses["resolve_comments"] == "done"
    assert statuses["close_round"] == "active"
    assert statuses["approved"] == "pending"
    assert template["summary"]["open_round_id"] == rid
    assert template["summary"]["open_comments"] == 0
    assert template["summary"]["resolved_comments"] == 1
    assert template["summary"]["blocking"] is False


def test_template_for_approved_version_marks_review_flow_done(fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    rid = round_repo.create_round(
        document_version_id=ver_id,
        reviewer_user_id="reviewer",
        initiated_by="admin",
    )
    round_repo.close_round(round_id=rid, outcome="approved")

    template = template_repo.default_review_template(ver_id)

    assert template["version_status"] == "approved"
    assert template["summary"]["latest_round_id"] == rid
    assert template["summary"]["latest_round_status"] == "closed"
    assert template["summary"]["latest_round_outcome"] == "approved"
    assert set(_step_statuses(template).values()) == {"done"}
