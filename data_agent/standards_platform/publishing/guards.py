"""Version state guards used by drafting + publishing handlers.

Wave 5: replaces Wave 4's _block_if_reviewing with a more general guard
that also covers 'released' (immutable) and 'approved' (waiting publish).
"""
from __future__ import annotations

from sqlalchemy import text
from starlette.responses import JSONResponse

from ...db_engine import get_engine


def is_version_released(version_id: str) -> bool:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT status FROM std_document_version WHERE id=:i"
        ), {"i": version_id}).first()
    return row is not None and row[0] == "released"


def block_if_not_drafting(version_id: str) -> JSONResponse | None:
    """Return 409 JSONResponse if version status != 'draft'.

    Replaces Wave 4's _block_if_reviewing. Carries clearer messaging:
      review     → 'version under review, drafting blocked'
      approved   → 'version status approved, drafting blocked'
      released   → 'version released, immutable'
      retired    → 'version status retired, drafting blocked'
      draft      → None (allow)

    Returns None for non-existent versions (downstream handler 404s).
    """
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT status FROM std_document_version WHERE id=:i"
        ), {"i": version_id}).first()
    if row is None:
        return None
    s = row[0]
    if s == "draft":
        return None
    if s == "review":
        return JSONResponse(
            {"error": "version under review, drafting blocked",
             "current_status": s},
            status_code=409,
        )
    if s == "released":
        return JSONResponse(
            {"error": "version released, immutable",
             "current_status": s},
            status_code=409,
        )
    return JSONResponse(
        {"error": f"version status '{s}', drafting blocked",
         "current_status": s},
        status_code=409,
    )
