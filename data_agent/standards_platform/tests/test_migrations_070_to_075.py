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


def _table_columns(table: str) -> set[str]:
    eng = get_engine()
    if eng is None:
        pytest.skip("DB unavailable")
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t"
        ), {"t": table}).fetchall()
        return {r[0] for r in rows}


def test_std_document_table_shape():
    cols = _table_columns("std_document")
    assert {"id", "doc_code", "title", "source_type", "source_url",
            "language", "status", "current_version_id", "owner_user_id",
            "tags", "raw_file_path", "last_error_log",
            "created_at", "updated_at", "created_by", "updated_by"} <= cols


def test_std_document_version_table_shape():
    cols = _table_columns("std_document_version")
    assert {"id", "document_id", "version_label",
            "semver_major", "semver_minor", "semver_patch",
            "released_at", "release_notes", "supersedes_version_id",
            "status", "snapshot_blob",
            "created_at", "updated_at", "created_by", "updated_by"} <= cols
