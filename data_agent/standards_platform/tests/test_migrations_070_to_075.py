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


def test_std_clause_shape_and_vector_dim():
    cols = _table_columns("std_clause")
    assert {"id","document_id","document_version_id","parent_clause_id",
            "ordinal_path","heading","clause_no","kind","body_md","body_html",
            "checksum","lock_holder","lock_expires_at","source_origin",
            "embedding"} <= cols
    eng = get_engine()
    with eng.connect() as conn:
        dim = conn.execute(text(
            "SELECT atttypmod FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid "
            "WHERE c.relname='std_clause' AND a.attname='embedding'"
        )).scalar()
        assert dim == 768, f"embedding dim must be 768, got {dim}"


def test_std_data_element_shape():
    cols = _table_columns("std_data_element")
    assert {"id","document_version_id","code","name_zh","name_en","definition",
            "representation_class","datatype","unit","value_domain_id",
            "obligation","cardinality","defined_by_clause_id","term_id",
            "data_classification","embedding"} <= cols


def test_std_value_domain_shape():
    cols = _table_columns("std_value_domain")
    assert {"id","document_version_id","code","name","kind",
            "defined_by_clause_id"} <= cols
    cols2 = _table_columns("std_value_domain_item")
    assert {"id","value_domain_id","value","label_zh","label_en","ordinal"} <= cols2


def test_std_term_shape():
    cols = _table_columns("std_term")
    assert {"id","document_version_id","term_code","name_zh","name_en",
            "definition","aliases","defined_by_clause_id","embedding"} <= cols


def test_std_reference_shape():
    cols = _table_columns("std_reference")
    assert {"id","source_clause_id","source_data_element_id","target_kind",
            "target_clause_id","target_document_id","target_url","target_doi",
            "snapshot_id","citation_text","confidence","verified_by",
            "verified_at"} <= cols


def test_std_web_snapshot_shape():
    cols = _table_columns("std_web_snapshot")
    assert {"id","url","http_status","fetched_at","html_path","pdf_path",
            "extracted_text","search_query"} <= cols


def test_std_search_session_and_hit():
    assert {"id","document_version_id","clause_id","author_user_id",
            "messages","created_at"} <= _table_columns("std_search_session")
    assert {"id","session_id","query","rank","snapshot_id","snippet"} \
        <= _table_columns("std_search_hit")
