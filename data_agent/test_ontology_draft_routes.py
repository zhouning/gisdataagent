from __future__ import annotations

from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api import ontology_draft_routes as routes
from data_agent.ontology.drafting import OntologyDraftConflict

DRAFT_ID = "11111111-1111-4111-8111-111111111111"


class _FakeService:
    def __init__(self):
        self.last_call = None
        self.append_error = None

    def list_drafts(self, **kwargs):
        self.last_call = ("list", kwargs)
        return []

    def create_draft(self, **kwargs):
        self.last_call = ("create", kwargs)
        return {
            "draft_id": DRAFT_ID,
            "base_content_sha256": "a" * 64,
            "status": "draft",
            "revision": 0,
            **kwargs,
        }

    def append_change(self, draft_id, **kwargs):
        self.last_call = ("append", draft_id, kwargs)
        if self.append_error:
            raise self.append_error
        return {
            "draft_id": draft_id,
            "change_id": "22222222-2222-4222-8222-222222222222",
            "revision": kwargs["expected_revision"] + 1,
            "operation": kwargs["operation"],
            "entity_type": kwargs["entity_type"],
            "entity_id": "gda:nr:class:Wetland",
        }

    def abandon(self, draft_id, **kwargs):
        self.last_call = ("abandon", draft_id, kwargs)
        return {
            "draft_id": draft_id,
            "status": "abandoned",
            "revision": kwargs["expected_revision"],
        }


class _IdempotentService(_FakeService):
    def __init__(self):
        super().__init__()
        self.revision = 0
        self.seen: dict[str, dict] = {}

    def append_change(self, draft_id, **kwargs):
        key = kwargs["idempotency_key"]
        if key in self.seen:
            return {**self.seen[key], "replayed": True}
        self.revision += 1
        result = super().append_change(draft_id, **kwargs)
        result["revision"] = self.revision
        self.seen[key] = result
        return result


def _client(monkeypatch, *, role="standard_editor", authenticated=True):
    service = _FakeService()
    user = object() if authenticated else None
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: user)
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("alice", role))
    monkeypatch.setattr(routes, "get_ontology_draft_service", lambda: service)
    monkeypatch.setattr(routes, "_audit", lambda *args, **kwargs: None)
    return TestClient(Starlette(routes=routes.get_ontology_draft_routes())), service


def _valid_change(**overrides):
    body = {
        "expected_revision": 0,
        "idempotency_key": "request-0001",
        "operation": "upsert_concept",
        "entity_type": "concept",
        "entity_id": "",
        "payload": {
            "code": "Wetland",
            "pref_label": "湿地",
            "domain_id": "02",
        },
        "actor": "mallory",
    }
    body.update(overrides)
    return body


def test_draft_routes_require_authentication(monkeypatch):
    client, _service = _client(monkeypatch, authenticated=False)
    response = client.post("/api/ontology/drafts", json={"title": "test"})
    assert response.status_code == 401


def test_only_editor_roles_can_create_or_change_drafts(monkeypatch):
    for role in ("viewer", "analyst", "standard_reviewer", "platform_operator"):
        client, _service = _client(monkeypatch, role=role)
        assert client.post("/api/ontology/drafts", json={"title": "test"}).status_code == 403
        assert (
            client.post(
                f"/api/ontology/drafts/{DRAFT_ID}/changes",
                json=_valid_change(),
            ).status_code
            == 403
        )

    for role in ("standard_editor", "admin"):
        client, service = _client(monkeypatch, role=role)
        response = client.post("/api/ontology/drafts", json={"title": "test"})
        assert response.status_code == 201
        assert service.last_call[1]["actor"] == "alice"


def test_standard_reviewer_can_read_draft_list(monkeypatch):
    client, _service = _client(monkeypatch, role="standard_reviewer")
    response = client.get("/api/ontology/drafts")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_append_uses_authenticated_actor_and_validates_request_contract(monkeypatch):
    client, service = _client(monkeypatch)
    response = client.post(
        f"/api/ontology/drafts/{DRAFT_ID}/changes",
        json=_valid_change(),
    )
    assert response.status_code == 201
    assert service.last_call[2]["actor"] == "alice"

    for invalid in (
        _valid_change(expected_revision=True),
        _valid_change(expected_revision=-1),
        _valid_change(payload=[]),
        _valid_change(idempotency_key=None),
        _valid_change(operation=[]),
    ):
        response = client.post(f"/api/ontology/drafts/{DRAFT_ID}/changes", json=invalid)
        assert response.status_code == 400
        assert response.json()["code"] == "draft_validation_error"


def test_revision_conflict_has_current_revision(monkeypatch):
    client, service = _client(monkeypatch)
    service.append_error = OntologyDraftConflict("draft revision is stale", current_revision=7)
    response = client.post(
        f"/api/ontology/drafts/{DRAFT_ID}/changes",
        json=_valid_change(),
    )
    assert response.status_code == 409
    assert response.json() == {
        "error": "draft revision is stale",
        "code": "draft_revision_conflict",
        "current_revision": 7,
    }


def test_same_idempotency_key_replay_does_not_advance_revision(monkeypatch):
    service = _IdempotentService()
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: object())
    monkeypatch.setattr(routes, "_set_user_context", lambda value: ("alice", "standard_editor"))
    monkeypatch.setattr(routes, "get_ontology_draft_service", lambda: service)
    monkeypatch.setattr(routes, "_audit", lambda *args, **kwargs: None)
    client = TestClient(Starlette(routes=routes.get_ontology_draft_routes()))
    body = _valid_change()
    first = client.post(f"/api/ontology/drafts/{DRAFT_ID}/changes", json=body)
    second = client.post(f"/api/ontology/drafts/{DRAFT_ID}/changes", json=body)
    assert first.status_code == second.status_code == 201
    assert second.json()["replayed"] is True
    assert service.revision == 1


def test_invalid_json_and_uuid_are_400(monkeypatch):
    client, _service = _client(monkeypatch)
    response = client.post(
        "/api/ontology/drafts",
        content=b"{",
        headers={"content-type": "application/json"},
    )
    bad_uuid = client.post("/api/ontology/drafts/not-a-uuid/changes", json=_valid_change())
    assert response.status_code == 400
    assert bad_uuid.status_code == 400


def test_cross_origin_write_is_rejected(monkeypatch):
    client, service = _client(monkeypatch)
    response = client.post(
        "/api/ontology/drafts",
        json={"title": "test"},
        headers={"Origin": "https://attacker.invalid"},
    )
    assert response.status_code == 403
    assert service.last_call is None


def test_internal_errors_are_sanitized(monkeypatch):
    client, service = _client(monkeypatch)
    service.append_error = RuntimeError("postgresql://secret@internal/db")
    response = client.post(
        f"/api/ontology/drafts/{DRAFT_ID}/changes",
        json=_valid_change(),
    )
    assert response.status_code == 503
    assert "secret" not in response.text


def test_abandon_keeps_authenticated_actor_and_revision_contract(monkeypatch):
    client, service = _client(monkeypatch)
    response = client.post(
        f"/api/ontology/drafts/{DRAFT_ID}/abandon",
        json={"expected_revision": 3},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "abandoned"
    assert service.last_call == (
        "abandon",
        DRAFT_ID,
        {"actor": "alice", "is_admin": False, "expected_revision": 3},
    )

    invalid = client.post(
        f"/api/ontology/drafts/{DRAFT_ID}/abandon",
        json={"expected_revision": True},
    )
    assert invalid.status_code == 400
    assert invalid.json()["code"] == "draft_validation_error"
