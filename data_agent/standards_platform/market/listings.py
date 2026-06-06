"""Market listing review workflow for released standards."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from ...db_engine import get_engine


LISTING_STATUSES = {"submitted", "approved", "rejected", "withdrawn"}
REVIEW_DECISIONS = {"approved", "rejected"}


def ensure_listing_table() -> None:
    """Create the listing table if migrations have not run yet."""
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS std_market_listing (
                id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                version_id      UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
                document_id     UUID NOT NULL REFERENCES std_document(id) ON DELETE CASCADE,
                status          TEXT NOT NULL DEFAULT 'submitted',
                submitted_by    TEXT NOT NULL,
                submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                reviewed_by     TEXT,
                reviewed_at     TIMESTAMPTZ,
                notes           TEXT,
                review_notes    TEXT,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT std_market_listing_status_check
                    CHECK (status IN ('submitted','approved','rejected','withdrawn')),
                CONSTRAINT std_market_listing_version_unique UNIQUE (version_id)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_std_market_listing_status
                ON std_market_listing(status, updated_at DESC)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_std_market_listing_document
                ON std_market_listing(document_id)
        """))


def submit_listing(*, version_id: str, submitted_by: str,
                   notes: str | None = None) -> dict[str, Any]:
    """Submit a released standard version for market review."""
    ensure_listing_table()
    eng = get_engine()
    with eng.begin() as conn:
        version = conn.execute(text("""
            SELECT id, document_id, status
              FROM std_document_version
             WHERE id = :v
        """), {"v": version_id}).mappings().first()
        if version is None:
            raise LookupError("version not found")
        if version["status"] != "released":
            raise ValueError("version must be released for market listing")

        row = conn.execute(text("""
            INSERT INTO std_market_listing
                (version_id, document_id, status, submitted_by, notes)
            VALUES
                (:v, :d, 'submitted', :u, :n)
            ON CONFLICT (version_id)
            DO UPDATE SET
                status = 'submitted',
                submitted_by = EXCLUDED.submitted_by,
                submitted_at = now(),
                reviewed_by = NULL,
                reviewed_at = NULL,
                notes = EXCLUDED.notes,
                review_notes = NULL,
                updated_at = now()
            RETURNING id
        """), {
            "v": version_id,
            "d": version["document_id"],
            "u": submitted_by,
            "n": notes,
        }).first()
        return _get_listing_by_id(conn, str(row[0]))


def review_listing(*, listing_id: str, decision: str, reviewed_by: str,
                   review_notes: str | None = None) -> dict[str, Any]:
    """Approve or reject a market listing."""
    ensure_listing_table()
    if decision not in REVIEW_DECISIONS:
        raise ValueError("decision must be approved or rejected")
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(text("""
            UPDATE std_market_listing
               SET status = :decision,
                   reviewed_by = :u,
                   reviewed_at = now(),
                   review_notes = :notes,
                   updated_at = now()
             WHERE id = :i
             RETURNING id
        """), {
            "i": listing_id,
            "decision": decision,
            "u": reviewed_by,
            "notes": review_notes,
        }).first()
        if row is None:
            raise LookupError("listing not found")
        return _get_listing_by_id(conn, str(row[0]))


def list_listings(*, status: str | None = None, limit: int = 50,
                  offset: int = 0) -> dict[str, Any]:
    """Return market listings for admin review."""
    ensure_listing_table()
    if status is not None and status not in LISTING_STATUSES:
        raise ValueError("invalid listing status")
    where: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        where.append("l.status = :status")
        params["status"] = status
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    eng = get_engine()
    with eng.connect() as conn:
        total = conn.execute(text(f"""
            SELECT count(*)
              FROM std_market_listing l
              JOIN std_document_version v ON v.id = l.version_id
              JOIN std_document d ON d.id = l.document_id
             {where_sql}
        """), params).scalar() or 0
        rows = conn.execute(text(_LISTING_SQL_BASE + f"""
             {where_sql}
             ORDER BY l.updated_at DESC, d.doc_code, v.version_label
             LIMIT :limit OFFSET :offset
        """), params).mappings().all()
    return {
        "items": [_row_to_listing(dict(row)) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }


_LISTING_SQL_BASE = """
    SELECT l.id,
           l.version_id,
           l.document_id,
           l.status,
           l.submitted_by,
           l.submitted_at,
           l.reviewed_by,
           l.reviewed_at,
           l.notes,
           l.review_notes,
           l.created_at,
           l.updated_at,
           d.doc_code,
           d.title,
           d.source_type,
           d.owner_user_id,
           v.version_label,
           v.released_at,
           v.updated_by AS released_by
      FROM std_market_listing l
      JOIN std_document_version v ON v.id = l.version_id
      JOIN std_document d ON d.id = l.document_id
"""


def _get_listing_by_id(conn, listing_id: str) -> dict[str, Any]:
    row = conn.execute(text(_LISTING_SQL_BASE + """
         WHERE l.id = :i
    """), {"i": listing_id}).mappings().first()
    if row is None:
        raise LookupError("listing not found")
    return _row_to_listing(dict(row))


def _row_to_listing(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "version_id": str(row["version_id"]),
        "document_id": str(row["document_id"]),
        "doc_code": row["doc_code"],
        "title": row["title"],
        "source_type": row["source_type"],
        "owner_user_id": row["owner_user_id"],
        "version_label": row["version_label"],
        "released_at": (
            row["released_at"].isoformat() if row.get("released_at") else None
        ),
        "released_by": row.get("released_by"),
        "status": row["status"],
        "submitted_by": row["submitted_by"],
        "submitted_at": (
            row["submitted_at"].isoformat() if row.get("submitted_at") else None
        ),
        "reviewed_by": row.get("reviewed_by"),
        "reviewed_at": (
            row["reviewed_at"].isoformat() if row.get("reviewed_at") else None
        ),
        "notes": row.get("notes"),
        "review_notes": row.get("review_notes"),
        "created_at": (
            row["created_at"].isoformat() if row.get("created_at") else None
        ),
        "updated_at": (
            row["updated_at"].isoformat() if row.get("updated_at") else None
        ),
    }
