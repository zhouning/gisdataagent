from starlette.testclient import TestClient

from data_agent.ontology_gateway_app import app


def test_gateway_health_is_available_without_authentication():
    with TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "ontology-gateway"}


def test_gateway_ontology_demo_requires_authentication():
    with TestClient(app) as client:
        response = client.get("/api/ontology/demo/overview")

    assert response.status_code == 401
