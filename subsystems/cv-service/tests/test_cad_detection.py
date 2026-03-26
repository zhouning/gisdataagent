import io
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _fake_file(name: str = "test.png") -> dict:
    return {"file": (name, io.BytesIO(b"\x89PNG fake"), "image/png")}


def test_detect_cad_layers_returns_layers():
    resp = client.post("/api/v1/detect/cad-layers", files=_fake_file())
    assert resp.status_code == 200
    data = resp.json()
    assert "layers" in data
    assert len(data["layers"]) >= 1
    assert data["layers"][0]["name"] == "建筑轮廓"


def test_detect_cad_layers_has_confidence():
    resp = client.post("/api/v1/detect/cad-layers", files=_fake_file())
    data = resp.json()
    assert 0.0 <= data["confidence"] <= 1.0


def test_detect_cad_topology_returns_issues():
    resp = client.post("/api/v1/detect/cad-topology", files=_fake_file())
    assert resp.status_code == 200
    data = resp.json()
    assert "issues" in data
    assert data["total_elements"] > 0
    assert all(i["type"] in ("gap", "overlap", "self_intersection") for i in data["issues"])
