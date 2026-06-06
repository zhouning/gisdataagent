"""Market listing review workflow for released standards."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from ...db_engine import get_engine


LISTING_STATUSES = {"submitted", "approved", "rejected", "withdrawn"}
REVIEW_DECISIONS = {"approved", "rejected"}
VISIBILITY_SCOPES = {"public", "organization", "private"}


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
                visibility_scope TEXT NOT NULL DEFAULT 'public',
                owner_org_id    TEXT,
                allowed_org_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
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
                CONSTRAINT std_market_listing_visibility_scope_check
                    CHECK (visibility_scope IN ('public','organization','private')),
                CONSTRAINT std_market_listing_version_unique UNIQUE (version_id)
            )
        """))
        conn.execute(text("""
            ALTER TABLE std_market_listing
                ADD COLUMN IF NOT EXISTS visibility_scope TEXT NOT NULL DEFAULT 'public'
        """))
        conn.execute(text("""
            ALTER TABLE std_market_listing
                ADD COLUMN IF NOT EXISTS owner_org_id TEXT
        """))
        conn.execute(text("""
            ALTER TABLE std_market_listing
                ADD COLUMN IF NOT EXISTS allowed_org_ids TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]
        """))
        conn.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_constraint
                     WHERE conname = 'std_market_listing_visibility_scope_check'
                ) THEN
                    ALTER TABLE std_market_listing
                        ADD CONSTRAINT std_market_listing_visibility_scope_check
                        CHECK (visibility_scope IN ('public','organization','private'));
                END IF;
            END $$
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_std_market_listing_status
                ON std_market_listing(status, updated_at DESC)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_std_market_listing_document
                ON std_market_listing(document_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_std_market_listing_visibility
                ON std_market_listing(visibility_scope)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_std_market_listing_owner_org
                ON std_market_listing(owner_org_id)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_std_market_listing_allowed_orgs
                ON std_market_listing USING GIN (allowed_org_ids)
        """))


def submit_listing(*, version_id: str, submitted_by: str,
                   notes: str | None = None,
                   visibility_scope: str = "public",
                   owner_org_id: str | None = None,
                   allowed_org_ids: list[str] | None = None) -> dict[str, Any]:
    """Submit a released standard version for market review."""
    ensure_listing_table()
    visibility_scope, owner_org_id, allowed_org_ids = _normalize_visibility(
        visibility_scope=visibility_scope,
        owner_org_id=owner_org_id,
        allowed_org_ids=allowed_org_ids,
    )
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
                (version_id, document_id, status, visibility_scope,
                 owner_org_id, allowed_org_ids, submitted_by, notes)
            VALUES
                (:v, :d, 'submitted', :scope, :org, :allowed, :u, :n)
            ON CONFLICT (version_id)
            DO UPDATE SET
                status = 'submitted',
                visibility_scope = EXCLUDED.visibility_scope,
                owner_org_id = EXCLUDED.owner_org_id,
                allowed_org_ids = EXCLUDED.allowed_org_ids,
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
            "scope": visibility_scope,
            "org": owner_org_id,
            "allowed": allowed_org_ids,
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


def update_listing_visibility(*, listing_id: str, visibility_scope: str,
                              owner_org_id: str | None = None,
                              allowed_org_ids: list[str] | None = None
                              ) -> dict[str, Any]:
    """Update visibility settings for an existing market listing."""
    ensure_listing_table()
    visibility_scope, owner_org_id, allowed_org_ids = _normalize_visibility(
        visibility_scope=visibility_scope,
        owner_org_id=owner_org_id,
        allowed_org_ids=allowed_org_ids,
    )
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(text("""
            UPDATE std_market_listing
               SET visibility_scope = :scope,
                   owner_org_id = :org,
                   allowed_org_ids = :allowed,
                   updated_at = now()
             WHERE id = :i
             RETURNING id
        """), {
            "i": listing_id,
            "scope": visibility_scope,
            "org": owner_org_id,
            "allowed": allowed_org_ids,
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
           l.visibility_scope,
           l.owner_org_id,
           l.allowed_org_ids,
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
        "visibility_scope": row.get("visibility_scope") or "public",
        "owner_org_id": row.get("owner_org_id"),
        "allowed_org_ids": list(row.get("allowed_org_ids") or []),
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


def _normalize_visibility(*, visibility_scope: str | None,
                          owner_org_id: str | None,
                          allowed_org_ids: list[str] | None
                          ) -> tuple[str, str | None, list[str]]:
    scope = (visibility_scope or "public").strip().lower()
    if scope not in VISIBILITY_SCOPES:
        raise ValueError("invalid visibility_scope")
    owner = owner_org_id.strip() if isinstance(owner_org_id, str) else None
    owner = owner or None
    allowed = []
    for org in allowed_org_ids or []:
        if not isinstance(org, str):
            continue
        normalized = org.strip()
        if normalized and normalized not in allowed:
            allowed.append(normalized)
    if scope == "organization" and not owner:
        raise ValueError("owner_org_id required for organization visibility")
    return scope, owner, allowed
