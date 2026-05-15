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


from datetime import datetime, timezone, timedelta
from data_agent.standards_platform.drafting.editor_session import (
    LockError, acquire_lock,
)


def _holder(db, cid):
    with db.connect() as c:
        return c.execute(_sql(
            "SELECT lock_holder, lock_expires_at FROM std_clause WHERE id=:i"
        ), {"i": cid}).first()


def test_acquire_lock_when_unlocked(db, clause_row):
    cid, _vid, _did = clause_row
    out = acquire_lock(cid, "alice")
    assert out["body_md"] == "initial body"
    assert out["checksum"]              # backfilled
    holder, exp = _holder(db, cid)
    assert holder == "alice"
    assert exp > datetime.now(timezone.utc) + timedelta(minutes=14)


def test_acquire_lock_when_held_by_other(db, clause_row):
    cid, _vid, _did = clause_row
    acquire_lock(cid, "alice")
    with pytest.raises(LockError) as exc:
        acquire_lock(cid, "bob")
    assert exc.value.holder == "alice"


def test_acquire_lock_when_expired_steals(db, clause_row):
    cid, _vid, _did = clause_row
    acquire_lock(cid, "alice")
    with db.begin() as c:
        c.execute(_sql(
            "UPDATE std_clause SET lock_expires_at = now() - interval '1 min' "
            "WHERE id=:i"
        ), {"i": cid})
    out = acquire_lock(cid, "bob")
    assert out["checksum"]
    holder, _exp = _holder(db, cid)
    assert holder == "bob"


def test_acquire_lock_same_user_renews(db, clause_row):
    cid, _vid, _did = clause_row
    acquire_lock(cid, "alice")
    out = acquire_lock(cid, "alice")
    assert out["body_md"] == "initial body"
    holder, _ = _holder(db, cid)
    assert holder == "alice"


def test_acquire_lock_clause_not_found(db):
    import uuid as _u
    with pytest.raises(LookupError):
        acquire_lock(str(_u.uuid4()), "alice")


from data_agent.standards_platform.drafting.editor_session import heartbeat
import time


def test_heartbeat_extends_expiry(db, clause_row):
    cid, _vid, _did = clause_row
    first = acquire_lock(cid, "alice")
    time.sleep(1)
    second = heartbeat(cid, "alice")
    assert second["lock_expires_at"] > first["lock_expires_at"]


def test_heartbeat_lost_lock_raises(db, clause_row):
    cid, _vid, _did = clause_row
    with pytest.raises(LockError):
        heartbeat(cid, "alice")


from data_agent.standards_platform.drafting.editor_session import (
    save_clause, ConflictError,
)


def test_save_clause_happy_path(db, clause_row):
    cid, _vid, _did = clause_row
    a = acquire_lock(cid, "alice")
    out = save_clause(cid, "alice",
                      if_match_checksum=a["checksum"],
                      body_md="updated body", body_html="<p>updated body</p>")
    assert out["checksum"] != a["checksum"]
    with db.connect() as c:
        row = c.execute(_sql(
            "SELECT body_md, body_html, updated_by FROM std_clause WHERE id=:i"
        ), {"i": cid}).first()
    assert row.body_md == "updated body"
    assert row.body_html == "<p>updated body</p>"
    assert row.updated_by == "alice"


def test_save_clause_checksum_mismatch_raises_conflict(db, clause_row):
    cid, _vid, _did = clause_row
    acquire_lock(cid, "alice")
    with pytest.raises(ConflictError) as exc:
        save_clause(cid, "alice",
                    if_match_checksum="0000000000000000",
                    body_md="x", body_html=None)
    assert exc.value.server_body_md == "initial body"


def test_save_clause_lost_lock_raises(db, clause_row):
    cid, _vid, _did = clause_row
    a = acquire_lock(cid, "alice")
    with db.begin() as c:
        c.execute(_sql(
            "UPDATE std_clause SET lock_holder=NULL WHERE id=:i"
        ), {"i": cid})
    with pytest.raises(LockError):
        save_clause(cid, "alice",
                    if_match_checksum=a["checksum"],
                    body_md="x", body_html=None)


from data_agent.standards_platform.drafting.editor_session import release_lock


def test_release_lock_idempotent(db, clause_row):
    cid, _vid, _did = clause_row
    acquire_lock(cid, "alice")
    release_lock(cid, "alice")
    release_lock(cid, "alice")  # second call: no-op, no exception
    holder, _ = _holder(db, cid)
    assert holder is None


from data_agent.standards_platform.drafting.editor_session import break_lock


def test_break_lock_writes_audit(db, clause_row):
    cid, _vid, _did = clause_row
    acquire_lock(cid, "alice")
    out = break_lock(cid, "admin_user")
    assert out["previous_holder"] == "alice"
    holder, _ = _holder(db, cid)
    assert holder is None
    with db.connect() as c:
        n = c.execute(_sql(
            "SELECT COUNT(*) FROM agent_audit_log "
            "WHERE username=:u AND action='std_clause.lock.break' "
            "AND details->>'clause_id'=:c "
            "AND details->>'previous_holder'='alice'"
        ), {"u": "admin_user", "c": cid}).scalar()
    assert n >= 1


def test_lazy_checksum_on_first_acquire(db, clause_row):
    cid, _vid, _did = clause_row
    # P0 inserts may have NULL checksum; ensure backfill happens
    with db.begin() as c:
        c.execute(_sql("UPDATE std_clause SET checksum=NULL WHERE id=:i"),
                  {"i": cid})
    out = acquire_lock(cid, "alice")
    assert out["checksum"]
    with db.connect() as c:
        chk = c.execute(_sql(
            "SELECT checksum FROM std_clause WHERE id=:i"
        ), {"i": cid}).scalar()
    assert chk == compute_checksum("initial body")


def test_save_clause_inserts_new_data_elements(db, clause_row):
    cid, _vid, _did = clause_row
    a = acquire_lock(cid, "alice")
    out = save_clause(cid, "alice",
                      if_match_checksum=a["checksum"],
                      body_md="x", body_html="<p>x</p>",
                      data_elements=[
                          {"code": "FOO", "name_zh": "foo", "datatype": "char(8)"},
                          {"code": "BAR", "name_zh": "bar", "datatype": "varchar(50)",
                           "obligation": "mandatory"},
                      ])
    assert out["data_elements"] == {"inserted": 2, "updated": 0, "deleted": 0}
    with db.connect() as c:
        rows = c.execute(_sql(
            "SELECT code, name_zh, datatype, obligation FROM std_data_element "
            "WHERE defined_by_clause_id=:i ORDER BY code"
        ), {"i": cid}).fetchall()
    assert [r.code for r in rows] == ["BAR", "FOO"]
    assert rows[0].obligation == "mandatory"


def test_save_clause_updates_changed_and_deletes_missing(db, clause_row):
    cid, _vid, _did = clause_row
    # First save: 2 elements
    a = acquire_lock(cid, "alice")
    save_clause(cid, "alice", if_match_checksum=a["checksum"],
                body_md="x", body_html=None,
                data_elements=[
                    {"code": "FOO", "name_zh": "foo-old", "datatype": "char(8)"},
                    {"code": "BAR", "name_zh": "bar", "datatype": "char(8)"},
                ])
    # Re-acquire (save changed checksum)
    a2 = acquire_lock(cid, "alice")
    # Second save: rename FOO, drop BAR, add BAZ
    out = save_clause(cid, "alice", if_match_checksum=a2["checksum"],
                      body_md="y", body_html=None,
                      data_elements=[
                          {"code": "FOO", "name_zh": "foo-new", "datatype": "char(8)"},
                          {"code": "BAZ", "name_zh": "baz", "datatype": "int"},
                      ])
    assert out["data_elements"] == {"inserted": 1, "updated": 1, "deleted": 1}
    with db.connect() as c:
        codes = [r.code for r in c.execute(_sql(
            "SELECT code FROM std_data_element "
            "WHERE defined_by_clause_id=:i ORDER BY code"
        ), {"i": cid}).fetchall()]
    assert codes == ["BAZ", "FOO"]


def test_save_clause_without_data_elements_param_skips_diff(db, clause_row):
    cid, _vid, _did = clause_row
    # Pre-seed an element
    with db.begin() as c:
        vid = c.execute(_sql(
            "SELECT document_version_id FROM std_clause WHERE id=:i"
        ), {"i": cid}).scalar()
        c.execute(_sql(
            "INSERT INTO std_data_element (document_version_id, code, "
            "name_zh, defined_by_clause_id) VALUES (:v, 'EXIST', 'e', :cl)"
        ), {"v": vid, "cl": cid})
    a = acquire_lock(cid, "alice")
    out = save_clause(cid, "alice", if_match_checksum=a["checksum"],
                      body_md="z", body_html=None)
    assert "data_elements" not in out
    with db.connect() as c:
        n = c.execute(_sql(
            "SELECT COUNT(*) FROM std_data_element WHERE defined_by_clause_id=:i"
        ), {"i": cid}).scalar()
    assert n == 1  # untouched


def test_save_clause_auto_parses_md_table_when_data_elements_omitted(db, clause_row):
    cid, _vid, _did = clause_row
    md = (
        "module preamble\n\n"
        "| 字段代码 | 字段名称 | 类型 | 长度 | 必选 |\n"
        "|----------|----------|------|------|------|\n"
        "| ZONE | 区域 | char | 8 | M |\n"
        "| LABEL | 标签 | varchar | 50 | O |\n"
    )
    a = acquire_lock(cid, "alice")
    out = save_clause(cid, "alice",
                      if_match_checksum=a["checksum"],
                      body_md=md, body_html=None)
    # auto-parsed two new elements, no explicit param needed
    assert out["data_elements"] == {"inserted": 2, "updated": 0, "deleted": 0}
    with db.connect() as c:
        codes = sorted(r.code for r in c.execute(_sql(
            "SELECT code FROM std_data_element WHERE defined_by_clause_id=:i"
        ), {"i": cid}).fetchall())
    assert codes == ["LABEL", "ZONE"]
