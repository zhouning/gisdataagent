import io
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _fake_file(name: str = "test.dxf") -> dict:
    return {"file": (name, io.BytesIO(b"fake dxf content"), "application/octet-stream")}


def test_parse_dxf_returns_layers():
    resp = client.post("/api/v1/parse/dxf", files=_fake_file("drawing.dxf"))
    assert resp.status_code == 200
    data = resp.json()
    assert "layers" in data
    assert len(data["layers"]) >= 1
    assert data["entity_count"] > 0


def test_parse_dxf_returns_entities():
    resp = client.post("/api/v1/parse/dxf", files=_fake_file())
    data = resp.json()
    assert len(data["entities"]) >= 1
    assert data["entities"][0]["entity_type"] in ("LINE", "LWPOLYLINE", "TEXT", "CIRCLE")


def test_parse_dwg_returns_status():
    resp = client.post("/api/v1/parse/dwg", files=_fake_file("drawing.dwg"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "converted_to_dxf"
    assert "layers" in data
