"""Schema-level checks for migration 081."""
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


def test_check_accepts_new_kinds():
    eng = _get_engine_or_skip()
    inserted_ids = []
    try:
        with eng.begin() as conn:
            for kind in ('value_range', 'value_pattern', 'value_codelist'):
                row = conn.execute(text(
                    "INSERT INTO agent_semantic_hints "
                    "(scope_type, scope_ref, hint_kind, hint_text_zh, "
                    " severity, trigger_keywords) VALUES "
                    "('column', :sr, :hk, :ht, 'info', "
                    " CAST('[]' AS jsonb)) RETURNING id"
                ), {"sr": f"test_081_{kind}.col", "hk": kind,
                     "ht": f"test {kind}"}).first()
                inserted_ids.append(row[0])
    finally:
        if inserted_ids:
            with eng.begin() as conn:
                conn.execute(text(
                    "DELETE FROM agent_semantic_hints WHERE id = ANY(:ids)"
                ), {"ids": inserted_ids})


def test_check_still_rejects_unknown_kind():
    eng = _get_engine_or_skip()
    with pytest.raises(IntegrityError):
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO agent_semantic_hints "
                "(scope_type, scope_ref, hint_kind, hint_text_zh, "
                " severity, trigger_keywords) VALUES "
                "('column', 'X.y', 'totally_bogus_kind', 'h', 'info', "
                " CAST('[]' AS jsonb))"
            ))


def test_old_kinds_still_accepted():
    eng = _get_engine_or_skip()
    inserted_ids = []
    try:
        with eng.begin() as conn:
            for kind in ('value_enum', 'unit_note', 'join_note'):
                row = conn.execute(text(
                    "INSERT INTO agent_semantic_hints "
                    "(scope_type, scope_ref, hint_kind, hint_text_zh, "
                    " severity, trigger_keywords) VALUES "
                    "('column', :sr, :hk, :ht, 'info', "
                    " CAST('[]' AS jsonb)) RETURNING id"
                ), {"sr": f"test_081_old_{kind}.col", "hk": kind,
                     "ht": f"test old {kind}"}).first()
                inserted_ids.append(row[0])
    finally:
        if inserted_ids:
            with eng.begin() as conn:
                conn.execute(text(
                    "DELETE FROM agent_semantic_hints WHERE id = ANY(:ids)"
                ), {"ids": inserted_ids})
