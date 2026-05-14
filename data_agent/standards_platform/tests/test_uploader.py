import io
import pytest
from sqlalchemy import text

from data_agent.db_engine import get_engine
from data_agent.standards_platform.ingestion.uploader import ingest_upload
from data_agent.user_context import current_user_id


@pytest.fixture
def db():
    eng = get_engine()
    if eng is None: pytest.skip("DB unavailable")
    yield eng
    with eng.connect() as c:
        c.execute(text("DELETE FROM std_document WHERE owner_user_id = 'u_test'"))
        c.commit()


def test_ingest_docx_creates_document_and_version(db, tmp_path):
    current_user_id.set("u_test")
    path = tmp_path / "GB-T-XXXXX-2022.docx"
    path.write_bytes(b"PK\x03\x04 fake-docx")
    doc_id, ver_id = ingest_upload(path, original_name="GB-T-XXXXX-2022.docx")
    with db.connect() as c:
        row = c.execute(text(
            "SELECT status, source_type, current_version_id FROM std_document WHERE id=:i"
        ), {"i": doc_id}).first()
    assert row.status == "ingested"
    assert str(row.current_version_id) == ver_id


def test_ingest_rejects_unknown_extension(tmp_path):
    current_user_id.set("u_test")
    path = tmp_path / "notes.txt"
    path.write_text("hi")
    with pytest.raises(ValueError, match="unsupported file type"):
        ingest_upload(path, original_name="notes.txt")


def test_ingest_enqueues_extract_event(db, tmp_path):
    current_user_id.set("u_test")
    path = tmp_path / "a.xmi"; path.write_text("<XMI></XMI>")
    doc_id, _ = ingest_upload(path, original_name="a.xmi")
    with db.connect() as c:
        row = c.execute(text(
            "SELECT event_type, payload FROM std_outbox "
            "WHERE payload->>'document_id' = :d"
        ), {"d": doc_id}).first()
    assert row.event_type == "extract_requested"
