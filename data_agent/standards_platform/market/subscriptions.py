"""Persistent user subscriptions for standards market items."""
from __future__ import annotations

from typing import Any

from sqlalchemy import text

from ...db_engine import get_engine


def ensure_subscription_table() -> None:
    """Create the subscription table if migrations have not run yet."""
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS std_market_subscription (
                id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                subscriber_user_id      TEXT NOT NULL,
                document_id             UUID NOT NULL REFERENCES std_document(id) ON DELETE CASCADE,
                source_version_id       UUID NOT NULL REFERENCES std_document_version(id) ON DELETE CASCADE,
                last_seen_version_id    UUID REFERENCES std_document_version(id) ON DELETE SET NULL,
                status                  TEXT NOT NULL DEFAULT 'active',
                notes                   TEXT,
                created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT std_market_subscription_status_check
                    CHECK (status IN ('active','cancelled')),
                CONSTRAINT std_market_subscription_user_doc_unique
                    UNIQUE (subscriber_user_id, document_id)
            )
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_std_market_subscription_user_status
                ON std_market_subscription(subscriber_user_id, status)
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_std_market_subscription_document
                ON std_market_subscription(document_id)
        """))


def subscribe(*, version_id: str, subscriber_user_id: str,
              notes: str | None = None) -> dict[str, Any]:
    """Subscribe a user to the document behind a released version."""
    ensure_subscription_table()
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
            raise ValueError("version must be released to subscribe")

        row = conn.execute(text("""
            INSERT INTO std_market_subscription
                (subscriber_user_id, document_id, source_version_id,
                 last_seen_version_id, status, notes)
            VALUES
                (:u, :d, :v, :v, 'active', :n)
            ON CONFLICT (subscriber_user_id, document_id)
            DO UPDATE SET
                source_version_id = EXCLUDED.source_version_id,
                last_seen_version_id = EXCLUDED.last_seen_version_id,
                status = 'active',
                notes = EXCLUDED.notes,
                updated_at = now()
            RETURNING id
        """), {
            "u": subscriber_user_id,
            "d": version["document_id"],
            "v": version_id,
            "n": notes,
        }).first()
        return _get_subscription_by_id(conn, str(row[0]))


def list_subscriptions(*, subscriber_user_id: str) -> list[dict[str, Any]]:
    ensure_subscription_table()
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(_LIST_SQL_BASE + """
             WHERE s.subscriber_user_id = :u AND s.status = 'active'
             ORDER BY s.updated_at DESC, d.doc_code
        """), {"u": subscriber_user_id}).mappings().all()
    return [_row_to_subscription(dict(row)) for row in rows]


def unsubscribe(*, subscription_id: str, subscriber_user_id: str,
                is_admin: bool = False) -> dict[str, Any]:
    ensure_subscription_table()
    eng = get_engine()
    with eng.begin() as conn:
        row = conn.execute(text("""
            UPDATE std_market_subscription
               SET status = 'cancelled', updated_at = now()
             WHERE id = :i
               AND (:is_admin OR subscriber_user_id = :u)
            RETURNING id
        """), {
            "i": subscription_id,
            "u": subscriber_user_id,
            "is_admin": is_admin,
        }).first()
        if row is None:
            raise LookupError("subscription not found")
        return _get_subscription_by_id(conn, str(row[0]))


def mark_seen(*, subscription_id: str, subscriber_user_id: str,
              is_admin: bool = False) -> dict[str, Any]:
    ensure_subscription_table()
    eng = get_engine()
    with eng.begin() as conn:
        sub = conn.execute(text("""
            SELECT id, document_id
              FROM std_market_subscription
             WHERE id = :i
               AND status = 'active'
               AND (:is_admin OR subscriber_user_id = :u)
             FOR UPDATE
        """), {
            "i": subscription_id,
            "u": subscriber_user_id,
            "is_admin": is_admin,
        }).mappings().first()
        if sub is None:
            raise LookupError("subscription not found")
        latest = _latest_released_version_id(conn, str(sub["document_id"]))
        if latest is None:
            raise LookupError("latest released version not found")
        conn.execute(text("""
            UPDATE std_market_subscription
               SET last_seen_version_id = :v, updated_at = now()
             WHERE id = :i
        """), {"v": latest, "i": subscription_id})
        return _get_subscription_by_id(conn, subscription_id)


_LIST_SQL_BASE = """
    SELECT s.id,
           s.subscriber_user_id,
           s.document_id,
           d.doc_code,
           d.title,
           s.source_version_id,
           sv.version_label AS source_version_label,
           s.last_seen_version_id,
           l.id AS latest_version_id,
           l.version_label AS latest_version_label,
           l.released_at AS latest_released_at,
           s.status,
           s.notes,
           s.created_at,
           s.updated_at
      FROM std_market_subscription s
      JOIN std_document d ON d.id = s.document_id
      JOIN std_document_version sv ON sv.id = s.source_version_id
      LEFT JOIN LATERAL (
          SELECT id, version_label, released_at
            FROM std_document_version
           WHERE document_id = s.document_id
             AND status = 'released'
           ORDER BY semver_major DESC, semver_minor DESC, semver_patch DESC,
                    released_at DESC NULLS LAST
           LIMIT 1
      ) l ON TRUE
"""


def _get_subscription_by_id(conn, subscription_id: str) -> dict[str, Any]:
    row = conn.execute(text(_LIST_SQL_BASE + """
         WHERE s.id = :i
    """), {"i": subscription_id}).mappings().first()
    if row is None:
        raise LookupError("subscription not found")
    return _row_to_subscription(dict(row))


def _latest_released_version_id(conn, document_id: str) -> str | None:
    row = conn.execute(text("""
        SELECT id
          FROM std_document_version
         WHERE document_id = :d AND status = 'released'
         ORDER BY semver_major DESC, semver_minor DESC, semver_patch DESC,
                  released_at DESC NULLS LAST
         LIMIT 1
    """), {"d": document_id}).first()
    return str(row[0]) if row else None


def _row_to_subscription(row: dict[str, Any]) -> dict[str, Any]:
    latest_id = str(row["latest_version_id"]) if row.get("latest_version_id") else None
    last_seen_id = (
        str(row["last_seen_version_id"])
        if row.get("last_seen_version_id") else None
    )
    return {
        "id": str(row["id"]),
        "subscriber_user_id": row["subscriber_user_id"],
        "document_id": str(row["document_id"]),
        "doc_code": row["doc_code"],
        "title": row["title"],
        "source_version_id": str(row["source_version_id"]),
        "source_version_label": row["source_version_label"],
        "last_seen_version_id": last_seen_id,
        "latest_version_id": latest_id,
        "latest_version_label": row.get("latest_version_label"),
        "latest_released_at": (
            row["latest_released_at"].isoformat()
            if row.get("latest_released_at") else None
        ),
        "has_update": bool(latest_id and latest_id != last_seen_id),
        "status": row["status"],
        "notes": row.get("notes"),
        "created_at": row["created_at"].isoformat()
            if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat()
            if row.get("updated_at") else None,
    }
