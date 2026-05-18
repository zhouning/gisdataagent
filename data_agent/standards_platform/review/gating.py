"""Close-round gating: pure SQL counts of pending refs + open comments."""
from __future__ import annotations

from sqlalchemy import text

from ...db_engine import get_engine


def check_close_gating(*, round_id: str, version_id: str) -> dict:
    """Return {pending_refs, open_comments, blocking}.

    blocking = True when at least one is > 0.
    Used by both /close-precheck endpoint and the close handler when
    outcome='approved'.
    """
    eng = get_engine()
    with eng.connect() as conn:
        pending = conn.execute(text("""
            SELECT count(*) FROM std_reference r
            JOIN std_clause c ON c.id = r.source_clause_id
            WHERE c.document_version_id = :v
              AND r.verification_status = 'pending'
        """), {"v": version_id}).scalar() or 0
        open_c = conn.execute(text("""
            SELECT count(*) FROM std_review_comment
             WHERE round_id = :r AND resolution = 'open'
        """), {"r": round_id}).scalar() or 0
    return {
        "pending_refs": int(pending),
        "open_comments": int(open_c),
        "blocking": int(pending) + int(open_c) > 0,
    }
