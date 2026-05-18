"""Schema-level checks for migration 080."""
from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from data_agent.db_engine import get_engine


def _get_engine_or_skip():
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)
    eng = get_engine()
    if eng is None:
        pytest.skip("DB engine unavailable")
    return eng


def test_derived_columns_exist():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='agent_semantic_hints'"
        )).fetchall()}
    assert "std_derived_link_id" in cols   # pre-existing from P0
    assert "std_version_id" in cols
    assert "derived_status" in cols


def test_derived_status_check_rejects_invalid():
    """derived_status must be NULL/'active'/'stale'."""
    eng = _get_engine_or_skip()
    with pytest.raises(IntegrityError):
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO agent_semantic_hints "
                "(scope_type, scope_ref, hint_kind, hint_text_zh, "
                " severity, trigger_keywords, derived_status) VALUES "
                "('column', 'X.y', 'other', 'h', 'info', "
                " CAST('[]' AS jsonb), 'bogus')"
            ))


def test_derived_status_accepts_active_and_stale():
    eng = _get_engine_or_skip()
    inserted_ids = []
    try:
        with eng.begin() as conn:
            for status in ('active', 'stale'):
                row = conn.execute(text(
                    "INSERT INTO agent_semantic_hints "
                    "(scope_type, scope_ref, hint_kind, hint_text_zh, "
                    " severity, trigger_keywords, derived_status) VALUES "
                    "('column', :sr, 'other', :ht, 'info', "
                    " CAST('[]' AS jsonb), :ds) RETURNING id"
                ), {"sr": f"test_080_{status}.col", "ht": f"test {status}",
                     "ds": status}).first()
                inserted_ids.append(row[0])
    finally:
        if inserted_ids:
            with eng.begin() as conn:
                conn.execute(text(
                    "DELETE FROM agent_semantic_hints WHERE id = ANY(:ids)"
                ), {"ids": inserted_ids})
