from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api import public_ontology_routes


class _FakeOntologyService:
    def status(self):
        return {
            "available": True,
            "package_dir": "/srv/gis-data-agent/ontology/packages/private",
            "stats": {"domain_class_count": 2},
        }

    def domains(self):
        return [{"domain_id": "land", "label": "地类图斑", "concept_count": 1}]

    def search_concepts(self, **kwargs):
        return {"items": [], "total": 0, "echo": kwargs}

    def get_concept(self, concept_id):
        if concept_id == "missing":
            return None
        return {"concept_id": concept_id, "pref_label": "地类图斑"}

    def get_properties(self, concept_id, **kwargs):
        return {"items": [], "total": 0, "group_counts": {}, "concept_id": concept_id}

    def get_relations(self, concept_id, **kwargs):
        return {"items": [], "total": 0, "concept_id": concept_id}

    def get_graph(self, **kwargs):
        return {"nodes": [], "edges": [], "node_count": 0, "edge_count": 0, "echo": kwargs}

    def get_mappings(self, **kwargs):
        return {"items": [], "total": 0, "echo": kwargs}

    def validation(self):
        return {"conforms": True, "issue_count": 0}


def _client(monkeypatch):
    monkeypatch.setattr(public_ontology_routes, "get_ontology_service", _FakeOntologyService)
    return TestClient(Starlette(routes=public_ontology_routes.get_public_ontology_routes()))


def test_public_ontology_is_readable_without_authentication(monkeypatch):
    with _client(monkeypatch) as client:
        response = client.get("/api/public/ontology/status")

    assert response.status_code == 200
    assert response.json()["available"] is True
    assert "package_dir" not in response.json()
    assert response.headers["x-robots-tag"] == "noindex, nofollow"


def test_public_ontology_is_get_only_and_bounded(monkeypatch):
    with _client(monkeypatch) as client:
        method_response = client.post("/api/public/ontology/status")
        limit_response = client.get("/api/public/ontology/concepts?limit=101")

    assert method_response.status_code == 405
    assert limit_response.status_code == 400


def test_public_ontology_concept_validation(monkeypatch):
    with _client(monkeypatch) as client:
        missing_parameter = client.get("/api/public/ontology/concept")
        missing_concept = client.get("/api/public/ontology/concept?concept_id=missing")
        concept = client.get("/api/public/ontology/concept?concept_id=land-parcel")

    assert missing_parameter.status_code == 400
    assert missing_concept.status_code == 404
    assert concept.status_code == 200
    assert concept.json()["concept_id"] == "land-parcel"
