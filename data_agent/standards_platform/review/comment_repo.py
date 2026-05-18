"""CRUD on std_review_comment."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import text

from ...db_engine import get_engine


def create_comment(*, round_id: str, clause_id: str,
                   author_user_id: str, body_md: str,
                   parent_comment_id: Optional[str] = None) -> str:
    cid = str(uuid.uuid4())
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_review_comment
                (id, round_id, clause_id, parent_comment_id,
                 author_user_id, body_md)
            VALUES (:i, :r, :c, :p, :a, :b)
        """), {"i": cid, "r": round_id, "c": clause_id,
                "p": parent_comment_id, "a": author_user_id,
                "b": body_md})
    return cid


def list_comments(*, round_id: str,
                  clause_id: Optional[str] = None) -> list[dict]:
    sql = ("SELECT id, round_id, clause_id, parent_comment_id, "
           "author_user_id, body_md, resolution, created_at, "
           "resolved_at, resolved_by FROM std_review_comment "
           "WHERE round_id=:r")
    params = {"r": round_id}
    if clause_id:
        sql += " AND clause_id=:c"
        params["c"] = clause_id
    sql += " ORDER BY created_at ASC"
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def get_comment(comment_id: str) -> Optional[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT id, round_id, clause_id, parent_comment_id, "
            "author_user_id, body_md, resolution, created_at, "
            "resolved_at, resolved_by FROM std_review_comment WHERE id=:i"
        ), {"i": comment_id}).mappings().first()
    return dict(row) if row else None


def resolve_comment(*, comment_id: str, resolution: str,
                    resolver_user_id: str) -> None:
    if resolution not in ("accepted", "rejected", "duplicate"):
        raise ValueError(f"invalid resolution: {resolution}")
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            UPDATE std_review_comment
               SET resolution=:r, resolved_by=:u, resolved_at=now()
             WHERE id=:i
        """), {"r": resolution, "u": resolver_user_id, "i": comment_id})
