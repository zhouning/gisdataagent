"""Schema-level checks for migration 079."""
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


def _seed_data_element(eng):
    """Returns (doc_id, ver_id, clause_id, element_id)."""
    doc_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    cid = str(uuid.uuid4())
    eid = str(uuid.uuid4())
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_document (id, doc_code, title, source_type, "
            "status, owner_user_id) VALUES (:i, :c, 't', 'draft', "
            "'ingested', 'admin')"
        ), {"i": doc_id, "c": f"T-079-{doc_id[:6]}"})
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
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation) VALUES (:i, :v, 'TEST', '测试', "
            "'string', 'optional')"
        ), {"i": eid, "v": ver_id})
    return doc_id, ver_id, cid, eid


def test_binding_columns_exist():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='std_data_element'"
        )).fetchall()}
    assert {"bound_table", "bound_column"}.issubset(cols)


def test_binding_check_rejects_partial():
    """All-or-none constraint: setting only bound_table must fail."""
    eng = _get_engine_or_skip()
    doc_id, ver_id, cid, eid = _seed_data_element(eng)
    try:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "UPDATE std_data_element SET bound_table='x' WHERE id=:i"
                ), {"i": eid})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_binding_accepts_both_set():
    """Both bound_table + bound_column set: must succeed."""
    eng = _get_engine_or_skip()
    doc_id, ver_id, cid, eid = _seed_data_element(eng)
    try:
        with eng.begin() as conn:
            conn.execute(text(
                "UPDATE std_data_element SET bound_table='cq_dltb', "
                "bound_column='dlbm' WHERE id=:i"
            ), {"i": eid})
        with eng.connect() as c:
            row = c.execute(text(
                "SELECT bound_table, bound_column FROM std_data_element "
                "WHERE id=:i"
            ), {"i": eid}).first()
        assert row[0] == 'cq_dltb' and row[1] == 'dlbm'
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_publish_event_table_exists():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='std_publish_event'"
        )).fetchall()}
    assert {"id", "document_version_id", "event_type", "actor_user_id",
            "occurred_at", "notes"}.issubset(cols)


def test_publish_event_type_check_rejects_invalid():
    eng = _get_engine_or_skip()
    doc_id, ver_id, cid, eid = _seed_data_element(eng)
    try:
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_publish_event (id, document_version_id, "
                    "event_type, actor_user_id) VALUES "
                    "(:i, :v, 'bogus', 'admin')"
                ), {"i": str(uuid.uuid4()), "v": ver_id})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_publish_event_type_accepts_published_and_forked():
    eng = _get_engine_or_skip()
    doc_id, ver_id, cid, eid = _seed_data_element(eng)
    try:
        with eng.begin() as conn:
            for et in ('published', 'forked'):
                conn.execute(text(
                    "INSERT INTO std_publish_event (id, document_version_id, "
                    "event_type, actor_user_id) VALUES "
                    "(:i, :v, :et, 'admin')"
                ), {"i": str(uuid.uuid4()), "v": ver_id, "et": et})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_derived_link_partial_unique_active():
    """Two 'active' links with same (strategy, target_kind, target_id) must conflict."""
    eng = _get_engine_or_skip()
    doc_id, ver_id, cid, eid = _seed_data_element(eng)
    l1 = str(uuid.uuid4())
    try:
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO std_derived_link (id, source_kind, source_id, "
                "source_version_id, target_kind, target_table, target_id, "
                "derivation_strategy, status) VALUES "
                "(:i, 'data_element', :s, :v, 'semantic_hint', "
                "'agent_semantic_hints', 'TG-1', 'to_semantic_hint', 'active')"
            ), {"i": l1, "s": eid, "v": ver_id})
        with pytest.raises(IntegrityError):
            with eng.begin() as conn:
                conn.execute(text(
                    "INSERT INTO std_derived_link (id, source_kind, source_id, "
                    "source_version_id, target_kind, target_table, target_id, "
                    "derivation_strategy, status) VALUES "
                    "(:i, 'data_element', :s, :v, 'semantic_hint', "
                    "'agent_semantic_hints', 'TG-1', 'to_semantic_hint', 'active')"
                ), {"i": str(uuid.uuid4()), "s": eid, "v": ver_id})
    finally:
        with eng.begin() as conn:
            conn.execute(text("DELETE FROM std_derived_link WHERE id=:i"),
                         {"i": l1})
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})


def test_derived_link_stale_allows_duplicate_target():
    """Multiple stale rows for same target should be permitted."""
    eng = _get_engine_or_skip()
    doc_id, ver_id, cid, eid = _seed_data_element(eng)
    l1, l2 = str(uuid.uuid4()), str(uuid.uuid4())
    try:
        with eng.begin() as conn:
            for lid in (l1, l2):
                conn.execute(text(
                    "INSERT INTO std_derived_link (id, source_kind, source_id, "
                    "source_version_id, target_kind, target_table, target_id, "
                    "derivation_strategy, status) VALUES "
                    "(:i, 'data_element', :s, :v, 'semantic_hint', "
                    "'agent_semantic_hints', 'TG-2', 'to_semantic_hint', 'stale')"
                ), {"i": lid, "s": eid, "v": ver_id})
    finally:
        with eng.begin() as conn:
            conn.execute(text(
                "DELETE FROM std_derived_link WHERE id IN (:a,:b)"
            ), {"a": l1, "b": l2})
            conn.execute(text("DELETE FROM std_document WHERE id=:i"),
                         {"i": doc_id})
