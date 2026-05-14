import uuid
import pytest
from sqlalchemy import text

from data_agent.db_engine import get_engine
from data_agent.standards_platform import repository as repo


@pytest.fixture
def fresh_doc():
    eng = get_engine()
    if eng is None:
        pytest.skip("DB unavailable")
    code = f"TEST-{uuid.uuid4().hex[:8]}"
    yield code
    with eng.connect() as conn:
        conn.execute(text(
            "DELETE FROM std_document WHERE doc_code = :c"
        ), {"c": code})
        conn.commit()


def test_create_document_and_initial_version(fresh_doc):
    doc_id = repo.create_document(
        doc_code=fresh_doc, title="测试标准", source_type="enterprise",
        owner_user_id="tester", raw_file_path="/tmp/x.docx",
    )
    assert isinstance(doc_id, str)
    ver_id = repo.create_version(document_id=doc_id, version_label="v1.0",
                                 created_by="tester")
    repo.set_current_version(doc_id, ver_id)
    doc = repo.get_document(doc_id)
    assert doc["doc_code"] == fresh_doc
    assert doc["current_version_id"] == ver_id


def test_list_documents_filters_by_owner(fresh_doc):
    repo.create_document(doc_code=fresh_doc, title="t", source_type="enterprise",
                          owner_user_id="alice", raw_file_path="/tmp/a")
    rows = repo.list_documents(owner_user_id="alice")
    codes = {r["doc_code"] for r in rows}
    assert fresh_doc in codes


def test_get_document_returns_none_for_missing():
    assert repo.get_document(str(uuid.uuid4())) is None
