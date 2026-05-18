"""Unit tests for publishing/{publish_repo, guards}."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.publishing import publish_repo, guards


@pytest.fixture
def fresh_approved_version(engine, fresh_clause):
    """fresh_clause + flip version to 'approved'."""
    cid, doc_id, ver_id = fresh_clause
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_document_version SET status='approved' WHERE id=:v"
        ), {"v": ver_id})
    return cid, doc_id, ver_id


@pytest.fixture
def fresh_released_version(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_document_version SET status='released', "
            "released_at=now() WHERE id=:v"
        ), {"v": ver_id})
    return cid, doc_id, ver_id


def test_publish_version_happy(engine, fresh_approved_version):
    cid, doc_id, ver_id = fresh_approved_version
    out = publish_repo.publish_version(version_id=ver_id, by_user="admin")
    try:
        assert out["status"] == "released"
        assert out["released_at"] is not None
        assert out["outbox_event_id"] is not None
        with engine.connect() as c:
            v = c.execute(text(
                "SELECT status FROM std_document_version WHERE id=:i"
            ), {"i": ver_id}).first()[0]
            ev = c.execute(text(
                "SELECT count(*) FROM std_publish_event WHERE document_version_id=:v "
                "AND event_type='published'"
            ), {"v": ver_id}).scalar()
            ob = c.execute(text(
                "SELECT count(*) FROM std_outbox WHERE id=:i AND event_type='version_released'"
            ), {"i": out["outbox_event_id"]}).scalar()
        assert v == "released"
        assert ev == 1
        assert ob == 1
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_outbox WHERE id=:i"),
                         {"i": out["outbox_event_id"]})


def test_publish_version_from_non_approved_raises(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause  # status='draft'
    with pytest.raises(ValueError, match="status must be approved"):
        publish_repo.publish_version(version_id=ver_id, by_user="admin")


def test_publish_version_already_released_raises(engine, fresh_released_version):
    cid, doc_id, ver_id = fresh_released_version
    with pytest.raises(ValueError, match="already released"):
        publish_repo.publish_version(version_id=ver_id, by_user="admin")


def test_publish_version_not_found_raises():
    with pytest.raises(LookupError):
        publish_repo.publish_version(
            version_id=str(uuid.uuid4()), by_user="admin"
        )


def test_fork_version_happy(engine, fresh_released_version):
    cid, doc_id, ver_id = fresh_released_version
    new_vid = publish_repo.fork_version(
        source_version_id=ver_id, new_label="v1.1", by_user="admin"
    )
    try:
        with engine.connect() as c:
            row = c.execute(text(
                "SELECT version_label, status, supersedes_version_id, "
                "semver_major, semver_minor FROM std_document_version WHERE id=:i"
            ), {"i": new_vid}).first()
            n_clauses = c.execute(text(
                "SELECT count(*) FROM std_clause WHERE document_version_id=:v"
            ), {"v": new_vid}).scalar()
            ev = c.execute(text(
                "SELECT count(*) FROM std_publish_event WHERE document_version_id=:v "
                "AND event_type='forked'"
            ), {"v": new_vid}).scalar()
        assert row[0] == "v1.1"
        assert row[1] == "draft"
        assert str(row[2]) == ver_id
        assert (row[3], row[4]) == (1, 1)
        assert n_clauses >= 1  # fresh_clause inserted 1
        assert ev == 1
    finally:
        with engine.begin() as conn:
            # fork created its own version row; cascade through std_document
            # would erase doc — instead just delete the new version, which
            # cascades to its own clauses.
            conn.execute(text(
                "DELETE FROM std_document_version WHERE id=:i"
            ), {"i": new_vid})


def test_fork_version_from_non_released_raises(engine, fresh_approved_version):
    cid, doc_id, ver_id = fresh_approved_version
    with pytest.raises(ValueError, match="must be released"):
        publish_repo.fork_version(
            source_version_id=ver_id, new_label="v1.1", by_user="admin"
        )


def test_fork_version_duplicate_label_raises(engine, fresh_released_version):
    cid, doc_id, ver_id = fresh_released_version
    new_vid = publish_repo.fork_version(
        source_version_id=ver_id, new_label="v1.1", by_user="admin"
    )
    try:
        # try forking again with the same label (re-release the source first)
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE std_document_version SET status='released' WHERE id=:i"
            ), {"i": ver_id})
        with pytest.raises(ValueError, match="already exists"):
            publish_repo.fork_version(
                source_version_id=ver_id, new_label="v1.1", by_user="admin"
            )
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM std_document_version WHERE id=:i"
            ), {"i": new_vid})


def test_fork_version_invalid_label_raises():
    with pytest.raises(ValueError, match="must match"):
        publish_repo.fork_version(
            source_version_id=str(uuid.uuid4()),
            new_label="not-a-version",
            by_user="admin",
        )


def test_list_published_versions_filter(engine, fresh_released_version):
    cid, doc_id, ver_id = fresh_released_version
    versions = publish_repo.list_published_versions(document_id=doc_id)
    assert any(str(v["id"]) == ver_id for v in versions)


def test_publish_timeline(engine, fresh_approved_version):
    cid, doc_id, ver_id = fresh_approved_version
    out = publish_repo.publish_version(version_id=ver_id, by_user="admin")
    try:
        events = publish_repo.get_publish_timeline(version_id=ver_id)
        assert len(events) == 1
        assert events[0]["event_type"] == "published"
        assert events[0]["actor_user_id"] == "admin"
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_outbox WHERE id=:i"),
                         {"i": out["outbox_event_id"]})


def test_block_if_not_drafting_draft_passes(fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    assert guards.block_if_not_drafting(ver_id) is None


def test_block_if_not_drafting_review_blocks(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE std_document_version SET status='review' WHERE id=:i"
        ), {"i": ver_id})
    resp = guards.block_if_not_drafting(ver_id)
    assert resp is not None
    assert resp.status_code == 409


def test_block_if_not_drafting_released_blocks(fresh_released_version):
    cid, doc_id, ver_id = fresh_released_version
    resp = guards.block_if_not_drafting(ver_id)
    assert resp is not None
    assert resp.status_code == 409
