"""CRUD on std_review_round."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import text

from ...db_engine import get_engine


def create_round(*, document_version_id: str, reviewer_user_id: str,
                 initiated_by: str) -> str:
    """Insert a new open round + flip version.status to 'review' atomically.

    Caller must verify version.status == 'draft' first (handler concern).
    Returns the new round_id.
    """
    rid = str(uuid.uuid4())
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_review_round
                (id, document_version_id, reviewer_user_id, initiated_by)
            VALUES (:i, :v, :r, :ib)
        """), {"i": rid, "v": document_version_id,
                "r": reviewer_user_id, "ib": initiated_by})
        conn.execute(text("""
            UPDATE std_document_version SET status='review'
             WHERE id=:v AND status='draft'
        """), {"v": document_version_id})
    return rid


def get_round(round_id: str) -> Optional[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT id, document_version_id, reviewer_user_id, initiated_by, "
            "initiated_at, closed_at, status, outcome "
            "FROM std_review_round WHERE id=:i"
        ), {"i": round_id}).mappings().first()
    return dict(row) if row else None


def list_rounds(*, version_id: Optional[str] = None,
                reviewer_user_id: Optional[str] = None,
                status: Optional[str] = None) -> list[dict]:
    where = []
    params = {}
    if version_id:
        where.append("document_version_id=:v"); params["v"] = version_id
    if reviewer_user_id:
        where.append("reviewer_user_id=:r"); params["r"] = reviewer_user_id
    if status:
        where.append("status=:s"); params["s"] = status
    sql = ("SELECT id, document_version_id, reviewer_user_id, initiated_by, "
           "initiated_at, closed_at, status, outcome FROM std_review_round")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY initiated_at DESC"
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def get_open_round_for_version(version_id: str) -> Optional[dict]:
    """Return the single open round for a version, if any."""
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT id, document_version_id, reviewer_user_id, initiated_by, "
            "initiated_at, closed_at, status, outcome "
            "FROM std_review_round WHERE document_version_id=:v AND status='open'"
        ), {"v": version_id}).mappings().first()
    return dict(row) if row else None


def close_round(*, round_id: str, outcome: str) -> dict:
    """Close the round, flip version.status accordingly.

    outcome: 'approved' -> version.status='approved'.
             'rejected' -> version.status='draft'.
    Caller is responsible for gating check (gating.check_close_gating)
    when outcome='approved'. Uses SELECT ... FOR UPDATE on the round
    to prevent concurrent close.

    Returns: {round_id, status, outcome, version_status}.
    """
    if outcome not in ("approved", "rejected"):
        raise ValueError(f"invalid outcome: {outcome}")
    target_version_status = "approved" if outcome == "approved" else "draft"
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(text(
            "SELECT document_version_id, status FROM std_review_round "
            "WHERE id=:i FOR UPDATE"
        ), {"i": round_id}).first()
        if row is None:
            raise LookupError("round not found")
        if row[0] is None:
            raise ValueError("round has no version")
        if row[1] == "closed":
            raise ValueError("round already closed")
        version_id = str(row[0])
        conn.execute(text(
            "UPDATE std_review_round SET status='closed', "
            "outcome=:o, closed_at=now() WHERE id=:i"
        ), {"o": outcome, "i": round_id})
        conn.execute(text(
            "UPDATE std_document_version SET status=:s WHERE id=:v"
        ), {"s": target_version_status, "v": version_id})
    return {"round_id": round_id, "status": "closed", "outcome": outcome,
            "version_status": target_version_status}
