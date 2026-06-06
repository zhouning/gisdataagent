"""Repository tests for Standards Platform market catalog + diff."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from data_agent.standards_platform.market import catalog


def _seed_document(engine, token: str) -> str:
    doc_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_document
                (id, doc_code, title, source_type, status, owner_user_id, tags)
            VALUES
                (:i, :c, :t, 'industry', 'published', 'market-admin',
                 ARRAY['market-test'])
        """), {
            "i": doc_id,
            "c": f"MKT-{token}-{doc_id[:6]}",
            "t": f"Market Test {token}",
        })
    return doc_id


def _seed_version(engine, doc_id: str, *, label: str = "v1.0",
                  status: str = "released") -> str:
    ver_id = str(uuid.uuid4())
    major, minor, patch = _semver(label)
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_document_version
                (id, document_id, version_label, status, semver_major,
                 semver_minor, semver_patch, released_at, updated_by)
            VALUES
                (:i, :d, :l, :s, :ma, :mi, :pa,
                 CASE WHEN :s = 'released' THEN now() ELSE NULL END,
                 'market-admin')
        """), {
            "i": ver_id, "d": doc_id, "l": label, "s": status,
            "ma": major, "mi": minor, "pa": patch,
        })
    return ver_id


def _seed_clause(engine, doc_id: str, version_id: str, ordinal: str,
                 *, clause_no: str | None = None, heading: str = "",
                 body_md: str = "") -> str:
    clause_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_clause
                (id, document_id, document_version_id, ordinal_path,
                 clause_no, heading, kind, body_md)
            VALUES
                (:i, :d, :v, CAST(:op AS ltree), :cn, :h, 'clause', :b)
        """), {
            "i": clause_id, "d": doc_id, "v": version_id,
            "op": ordinal, "cn": clause_no, "h": heading, "b": body_md,
        })
    return clause_id


def _seed_data_element(engine, version_id: str, code: str, *,
                       name: str, definition: str = "",
                       datatype: str = "text") -> str:
    element_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_data_element
                (id, document_version_id, code, name_zh, definition, datatype)
            VALUES
                (:i, :v, :c, :n, :d, :dt)
        """), {
            "i": element_id, "v": version_id, "c": code,
            "n": name, "d": definition, "dt": datatype,
        })
    return element_id


def _seed_term(engine, version_id: str, code: str) -> str:
    term_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_term (id, document_version_id, term_code, name_zh)
            VALUES (:i, :v, :c, :n)
        """), {"i": term_id, "v": version_id, "c": code, "n": code})
    return term_id


def _seed_value_domain(engine, version_id: str, code: str) -> str:
    domain_id = str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_value_domain
                (id, document_version_id, code, name, kind)
            VALUES (:i, :v, :c, :n, 'enumeration')
        """), {"i": domain_id, "v": version_id, "c": code, "n": code})
    return domain_id


def _delete_document(engine, doc_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM std_document WHERE id=:i"), {"i": doc_id})


def _semver(label: str) -> tuple[int, int, int]:
    parts = label.lstrip("v").split(".")
    return int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 0


def test_market_catalog_lists_only_released_versions(engine):
    token = f"released-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    released = _seed_version(engine, doc_id, label="v1.0", status="released")
    draft = _seed_version(engine, doc_id, label="v1.1", status="draft")
    try:
        result = catalog.list_market_standards(query=token)
        ids = {item["version_id"] for item in result["items"]}

        assert released in ids
        assert draft not in ids
    finally:
        _delete_document(engine, doc_id)


def test_market_catalog_supports_query_and_pagination(engine):
    token = f"paging-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    _seed_version(engine, doc_id, label="v1.0", status="released")
    _seed_version(engine, doc_id, label="v1.1", status="released")
    try:
        result = catalog.list_market_standards(
            query=token, limit=1, offset=1,
        )

        assert result["total"] == 2
        assert result["limit"] == 1
        assert result["offset"] == 1
        assert len(result["items"]) == 1
    finally:
        _delete_document(engine, doc_id)


def test_market_catalog_includes_asset_counts(engine):
    token = f"counts-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    version_id = _seed_version(engine, doc_id, status="released")
    _seed_clause(engine, doc_id, version_id, "1", clause_no="1")
    _seed_clause(engine, doc_id, version_id, "2", clause_no="2")
    _seed_data_element(engine, version_id, "DE-1", name="要素一")
    _seed_term(engine, version_id, "TERM-1")
    _seed_value_domain(engine, version_id, "VD-1")
    try:
        item = catalog.list_market_standards(query=token)["items"][0]

        assert item["asset_counts"] == {
            "clauses": 2,
            "data_elements": 1,
            "terms": 1,
            "value_domains": 1,
        }
    finally:
        _delete_document(engine, doc_id)


def test_market_diff_reports_structural_changes(engine):
    token = f"diff-{uuid.uuid4().hex[:8]}"
    doc_id = _seed_document(engine, token)
    source = _seed_version(engine, doc_id, label="v1.0", status="released")
    target = _seed_version(engine, doc_id, label="v1.1", status="released")

    _seed_clause(engine, doc_id, source, "1", clause_no="1",
                 heading="Same", body_md="same")
    _seed_clause(engine, doc_id, target, "1", clause_no="1",
                 heading="Same", body_md="same")
    _seed_clause(engine, doc_id, source, "2", clause_no="2",
                 heading="Changed", body_md="old")
    _seed_clause(engine, doc_id, target, "2", clause_no="2",
                 heading="Changed", body_md="new")
    _seed_clause(engine, doc_id, source, "3", clause_no="3",
                 heading="Removed", body_md="old")
    _seed_clause(engine, doc_id, target, "4", clause_no="4",
                 heading="Added", body_md="new")

    _seed_data_element(engine, source, "DE-A", name="相同", definition="same")
    _seed_data_element(engine, target, "DE-A", name="相同", definition="same")
    _seed_data_element(engine, source, "DE-B", name="变化", definition="old")
    _seed_data_element(engine, target, "DE-B", name="变化", definition="new")
    _seed_data_element(engine, source, "DE-C", name="删除", definition="old")
    _seed_data_element(engine, target, "DE-D", name="新增", definition="new")
    try:
        diff = catalog.version_diff(source, target)
        by_type = diff["summary"]["by_asset_type"]

        assert by_type["clauses"] == {
            "added": 1, "removed": 1, "changed": 1, "unchanged": 1,
        }
        assert by_type["data_elements"] == {
            "added": 1, "removed": 1, "changed": 1, "unchanged": 1,
        }
        assert diff["summary"]["added"] == 2
        assert diff["summary"]["removed"] == 2
        assert diff["summary"]["changed"] == 2
        assert diff["summary"]["unchanged"] == 2
        assert {
            (change["asset_type"], change["key"], change["change_type"])
            for change in diff["changes"]
        } >= {
            ("clauses", "2", "changed"),
            ("clauses", "3", "removed"),
            ("clauses", "4", "added"),
            ("data_elements", "DE-B", "changed"),
        }
    finally:
        _delete_document(engine, doc_id)


def test_market_diff_missing_version_raises_lookup_error(engine, fresh_clause):
    _, _, version_id = fresh_clause

    with pytest.raises(LookupError, match="version not found"):
        catalog.version_diff(version_id, str(uuid.uuid4()))
