"""Unit tests for derivation/link_repo."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from data_agent.standards_platform.derivation import link_repo


def _seed_data_element(engine, ver_id):
    """Insert a data element into the given version. Returns element_id."""
    eid = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_data_element (id, document_version_id, code, "
            "name_zh, datatype, obligation) VALUES (:i, :v, :c, '测试', "
            "'string', 'optional')"
        ), {"i": eid, "v": ver_id, "c": f"TEST-{eid[:6]}"})
    return eid


def test_create_link_get_link_round_trip(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    eid = _seed_data_element(engine, ver_id)
    target_id = f"tg-{uuid.uuid4()}"
    lid = link_repo.create_link(
        version_id=ver_id, source_kind="data_element", source_id=eid,
        derivation_strategy="to_semantic_hint", target_kind="semantic_hint",
        target_table="agent_semantic_hints", target_id=target_id,
        by_user="admin",
    )
    try:
        link = link_repo.get_link(lid)
        assert link is not None
        assert link["status"] == "active"
        assert link["derivation_strategy"] == "to_semantic_hint"
        assert link["target_id"] == target_id
        assert str(link["source_id"]) == eid
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_derived_link WHERE id=:i"),
                         {"i": lid})


def test_list_links_by_version_filters(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    eid = _seed_data_element(engine, ver_id)
    lid1 = link_repo.create_link(
        version_id=ver_id, source_kind="data_element", source_id=eid,
        derivation_strategy="to_semantic_hint", target_kind="semantic_hint",
        target_table="agent_semantic_hints", target_id=f"tg-{uuid.uuid4()}",
    )
    try:
        all_links = link_repo.list_links_by_version(version_id=ver_id)
        by_strategy = link_repo.list_links_by_version(
            version_id=ver_id, derivation_strategy="to_semantic_hint"
        )
        by_status = link_repo.list_links_by_version(
            version_id=ver_id, status="active"
        )
        none_match = link_repo.list_links_by_version(
            version_id=ver_id, derivation_strategy="to_synonym"
        )
        assert any(str(l["id"]) == lid1 for l in all_links)
        assert any(str(l["id"]) == lid1 for l in by_strategy)
        assert any(str(l["id"]) == lid1 for l in by_status)
        assert none_match == []
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_derived_link WHERE id=:i"),
                         {"i": lid1})


def test_list_active_links_for_doc_spans_versions(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    eid = _seed_data_element(engine, ver_id)
    lid = link_repo.create_link(
        version_id=ver_id, source_kind="data_element", source_id=eid,
        derivation_strategy="to_semantic_hint", target_kind="semantic_hint",
        target_table="agent_semantic_hints", target_id=f"tg-{uuid.uuid4()}",
    )
    try:
        active = link_repo.list_active_links_for_doc(
            document_id=doc_id, derivation_strategy="to_semantic_hint"
        )
        assert any(str(l["id"]) == lid for l in active)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_derived_link WHERE id=:i"),
                         {"i": lid})


def test_mark_stale_bulk(engine, fresh_clause):
    cid, doc_id, ver_id = fresh_clause
    eid = _seed_data_element(engine, ver_id)
    lid1 = link_repo.create_link(
        version_id=ver_id, source_kind="data_element", source_id=eid,
        derivation_strategy="to_semantic_hint", target_kind="semantic_hint",
        target_table="agent_semantic_hints", target_id=f"a-{uuid.uuid4()}",
    )
    lid2 = link_repo.create_link(
        version_id=ver_id, source_kind="data_element", source_id=eid,
        derivation_strategy="to_semantic_hint", target_kind="semantic_hint",
        target_table="agent_semantic_hints", target_id=f"b-{uuid.uuid4()}",
    )
    try:
        n = link_repo.mark_stale(link_ids=[lid1, lid2], reason="test")
        assert n == 2
        with engine.connect() as c:
            statuses = [r[0] for r in c.execute(text(
                "SELECT status FROM std_derived_link "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"ids": [lid1, lid2]}).fetchall()]
        assert statuses == ["stale", "stale"]
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "DELETE FROM std_derived_link "
                "WHERE id = ANY(CAST(:ids AS uuid[]))"
            ), {"ids": [lid1, lid2]})


def test_partial_unique_active_blocks_duplicate(engine, fresh_clause):
    """create_link a second time with same target while first is active → IntegrityError."""
    cid, doc_id, ver_id = fresh_clause
    eid = _seed_data_element(engine, ver_id)
    target_id = f"dup-{uuid.uuid4()}"
    lid1 = link_repo.create_link(
        version_id=ver_id, source_kind="data_element", source_id=eid,
        derivation_strategy="to_semantic_hint", target_kind="semantic_hint",
        target_table="agent_semantic_hints", target_id=target_id,
    )
    try:
        with pytest.raises(IntegrityError):
            link_repo.create_link(
                version_id=ver_id, source_kind="data_element", source_id=eid,
                derivation_strategy="to_semantic_hint", target_kind="semantic_hint",
                target_table="agent_semantic_hints", target_id=target_id,
            )
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM std_derived_link WHERE id=:i"),
                         {"i": lid1})
