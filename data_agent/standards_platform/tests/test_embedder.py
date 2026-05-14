from unittest.mock import patch
import pytest
from sqlalchemy import text
from data_agent.db_engine import get_engine
from data_agent.standards_platform.analysis.embedder import embed_version


def test_embed_writes_vectors_for_all_three_entities():
    eng = get_engine()
    if eng is None: pytest.skip("DB unavailable")
    # seed a version with 1 clause + 1 data_element + 1 term
    import uuid
    ver_id = str(uuid.uuid4()); doc_id = str(uuid.uuid4())
    with eng.connect() as c:
        c.execute(text("INSERT INTO std_document (id, doc_code, title, source_type, "
                       "owner_user_id) VALUES (:i, :c, 't', 'draft', 'u')"),
                  {"i": doc_id, "c": f"T-{uuid.uuid4().hex[:6]}"})
        c.execute(text("INSERT INTO std_document_version (id, document_id, version_label, "
                       "semver_major) VALUES (:i, :d, 'v1.0', 1)"),
                  {"i": ver_id, "d": doc_id})
        c.execute(text("INSERT INTO std_clause (id, document_id, document_version_id, "
                       "ordinal_path, kind, body_md) VALUES (:i, :d, :v, '5.2'::ltree, "
                       "'clause', 'some body text')"),
                  {"i": str(uuid.uuid4()), "d": doc_id, "v": ver_id})
        c.execute(text("INSERT INTO std_data_element (document_version_id, code, "
                       "name_zh, definition) VALUES (:v, 'X', 'x', 'x def')"), {"v": ver_id})
        c.execute(text("INSERT INTO std_term (document_version_id, term_code, name_zh) "
                       "VALUES (:v, 'T1', 't1')"), {"v": ver_id})
        c.commit()

    fake = [[0.1] * 768] * 3
    with patch("data_agent.standards_platform.analysis.embedder.get_embeddings",
               return_value=fake), \
         patch("data_agent.standards_platform.analysis.embedder.get_active_dimension",
               return_value=768):
        report = embed_version(version_id=ver_id)

    assert report["clauses_embedded"] >= 1
    assert report["data_elements_embedded"] >= 1
    assert report["terms_embedded"] >= 1

    with eng.connect() as c:
        row = c.execute(text("SELECT embedding IS NOT NULL AS has FROM std_clause "
                             "WHERE document_version_id=:v"), {"v": ver_id}).first()
        assert row.has


def test_embed_graceful_on_gateway_failure():
    import uuid
    with patch("data_agent.standards_platform.analysis.embedder.get_embeddings",
               return_value=[]):
        report = embed_version(version_id=str(uuid.uuid4()))
    assert report["clauses_embedded"] == 0
