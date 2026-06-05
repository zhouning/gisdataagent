import io, pytest
from unittest.mock import patch
from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.frontend_api import mount_frontend_api


def _client():
    app = Starlette()
    mount_frontend_api(app)
    return TestClient(app, raise_server_exceptions=False)


def _auth_user(monkeypatch, username="alice", role="standard_editor"):
    class U: pass
    u = U(); u.identifier = username; u.metadata = {"role": role}
    monkeypatch.setattr("data_agent.api.helpers._get_user_from_request", lambda r: u)


def test_list_documents_requires_auth(monkeypatch):
    monkeypatch.setattr("data_agent.api.helpers._get_user_from_request", lambda r: None)
    r = _client().get("/api/std/documents")
    assert r.status_code == 401


def test_upload_creates_document(monkeypatch):
    _auth_user(monkeypatch)
    with patch("data_agent.api.standards_routes.ingest_upload",
               return_value=("d1", "v1")):
        files = {"file": ("g.docx", io.BytesIO(b"PK"), "application/octet-stream")}
        r = _client().post("/api/std/documents", files=files,
                            data={"source_type": "national"})
    assert r.status_code == 200
    assert r.json()["document_id"] == "d1"


def test_viewer_cannot_upload(monkeypatch):
    _auth_user(monkeypatch, role="viewer")
    files = {"file": ("g.docx", io.BytesIO(b"PK"), "application/octet-stream")}
    r = _client().post("/api/std/documents", files=files,
                        data={"source_type": "national"})
    assert r.status_code == 403


def test_outbox_status_admin_only(monkeypatch):
    _auth_user(monkeypatch, role="standard_editor")
    r = _client().get("/api/std/outbox/status")
    assert r.status_code == 403
    _auth_user(monkeypatch, role="admin")
    with patch(
        "data_agent.api.standards_routes._outbox_admin.get_counts",
        return_value={"pending": 0, "in_flight": 0, "done": 0, "failed": 0},
    ) as get_counts:
        r = _client().get("/api/std/outbox/status")
    assert r.status_code == 200
    assert r.json() == {
        "counts": {"pending": 0, "in_flight": 0, "done": 0, "failed": 0}
    }
    get_counts.assert_called_once_with()
