"""CRUD on std_derived_link.

Uses **actual** column names: source_version_id (not document_version_id),
derivation_strategy (not strategy), status ∈ pending/active/stale/overridden/superseded.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import text

from ...db_engine import get_engine


def create_link(*, version_id: str, source_kind: str, source_id: str,
                derivation_strategy: str, target_kind: str,
                target_table: str, target_id: str,
                by_user: str = "system",
                notes: Optional[str] = None) -> str:
    lid = str(uuid.uuid4())
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO std_derived_link "
            "(id, source_kind, source_id, source_version_id, "
            " target_kind, target_table, target_id, "
            " derivation_strategy, status, stale_reason) "
            "VALUES (:i, :sk, :si, :v, :tk, :tt, :ti, :ds, 'active', :n)"
        ), {"i": lid, "sk": source_kind, "si": source_id, "v": version_id,
             "tk": target_kind, "tt": target_table, "ti": target_id,
             "ds": derivation_strategy, "n": notes})
    return lid


def get_link(link_id: str) -> Optional[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT id, source_kind, source_id, source_version_id, "
            "target_kind, target_table, target_id, derivation_strategy, "
            "status, stale_reason, generated_at "
            "FROM std_derived_link WHERE id=:i"
        ), {"i": link_id}).mappings().first()
    return dict(row) if row else None


def list_links_by_version(*, version_id: str,
                          derivation_strategy: Optional[str] = None,
                          status: Optional[str] = None) -> list[dict]:
    sql = (
        "SELECT id, source_kind, source_id, source_version_id, target_kind, "
        "target_table, target_id, derivation_strategy, status, stale_reason, "
        "generated_at FROM std_derived_link WHERE source_version_id=:v"
    )
    params: dict = {"v": version_id}
    if derivation_strategy:
        sql += " AND derivation_strategy=:s"
        params["s"] = derivation_strategy
    if status:
        sql += " AND status=:st"
        params["st"] = status
    sql += " ORDER BY generated_at DESC"
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def list_active_links_for_doc(*, document_id: str,
                              derivation_strategy: str) -> list[dict]:
    """All active links across all versions of a document."""
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT l.id, l.source_kind, l.source_id, l.source_version_id, "
            "l.target_kind, l.target_table, l.target_id, "
            "l.derivation_strategy, l.status, l.generated_at "
            "FROM std_derived_link l "
            "JOIN std_document_version v ON v.id = l.source_version_id "
            "WHERE v.document_id=:d AND l.derivation_strategy=:s "
            "AND l.status='active' "
            "ORDER BY l.generated_at DESC"
        ), {"d": document_id, "s": derivation_strategy}).mappings().all()
    return [dict(r) for r in rows]


def mark_stale(*, link_ids: list[str], reason: Optional[str] = None) -> int:
    if not link_ids:
        return 0
    eng = get_engine()
    with eng.begin() as conn:
        result = conn.execute(text(
            "UPDATE std_derived_link SET status='stale', stale_reason=:r "
            "WHERE id = ANY(CAST(:ids AS uuid[]))"
        ), {"r": reason or "superseded by new version", "ids": link_ids})
        return result.rowcount
