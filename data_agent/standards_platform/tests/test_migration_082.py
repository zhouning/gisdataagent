"""Schema-level checks for migration 082."""
from __future__ import annotations

import json
import os

import pytest
from dotenv import load_dotenv
from sqlalchemy import text

from data_agent.db_engine import get_engine


def _get_engine_or_skip():
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path, override=False)
    eng = get_engine()
    if eng is None:
        pytest.skip("DB engine unavailable")
    return eng


def test_derived_synonyms_column_exists():
    eng = _get_engine_or_skip()
    with eng.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='agent_semantic_sources'"
        )).fetchall()}
    assert "derived_synonyms" in cols
    assert "synonyms" in cols  # manual column unchanged


def test_derived_synonyms_default_empty_array():
    """New rows get '[]' as default — strategies upsert from there."""
    eng = _get_engine_or_skip()
    inserted_id = None
    try:
        with eng.begin() as conn:
            row = conn.execute(text(
                "INSERT INTO agent_semantic_sources "
                "(table_name, display_name, description, owner_username) "
                "VALUES (:t, :d, :desc, 'test_082') RETURNING id, derived_synonyms"
            ), {"t": f"test_082_{os.getpid()}",
                 "d": "test default",
                 "desc": "test"}).first()
            inserted_id = row[0]
            assert row[1] == [] or row[1] == "[]"
    finally:
        if inserted_id:
            with eng.begin() as conn:
                conn.execute(text(
                    "DELETE FROM agent_semantic_sources WHERE id=:i"
                ), {"i": inserted_id})


def test_derived_synonyms_stores_jsonb_array():
    """Round-trip a derived synonym list."""
    eng = _get_engine_or_skip()
    inserted_id = None
    try:
        with eng.begin() as conn:
            row = conn.execute(text(
                "INSERT INTO agent_semantic_sources "
                "(table_name, display_name, description, owner_username, "
                " derived_synonyms) "
                "VALUES (:t, :d, :desc, 'test_082', "
                " CAST(:ds AS jsonb)) RETURNING id, derived_synonyms"
            ), {"t": f"test_082_rt_{os.getpid()}",
                 "d": "round trip",
                 "desc": "rt",
                 "ds": json.dumps(["地类编码", "图斑面积", "land class"])}).first()
            inserted_id = row[0]
            stored = row[1]
            if isinstance(stored, str):
                stored = json.loads(stored)
            assert "地类编码" in stored
            assert "图斑面积" in stored
            assert "land class" in stored
    finally:
        if inserted_id:
            with eng.begin() as conn:
                conn.execute(text(
                    "DELETE FROM agent_semantic_sources WHERE id=:i"
                ), {"i": inserted_id})
