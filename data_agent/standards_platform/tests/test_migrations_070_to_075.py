"""Migration 070-075 smoke tests — applied cleanly + extensions present."""
import pytest
from sqlalchemy import text

from data_agent.db_engine import get_engine


def _has_extension(name: str) -> bool:
    eng = get_engine()
    if eng is None:
        pytest.skip("DB unavailable")
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = :n"),
            {"n": name},
        ).first()
        return row is not None


def test_ltree_extension_present_after_070():
    assert _has_extension("ltree"), "migration 070 must enable ltree"


def test_pgvector_extension_present():
    assert _has_extension("vector"), "pgvector is a system requirement"
