import io
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _fake_file(name: str = "model.obj") -> dict:
    return {"file": (name, io.BytesIO(b"fake 3d model"), "application/octet-stream")}


def test_parse_obj_returns_mesh_info():
    resp = client.post("/api/v1/parse/obj", files=_fake_file("building.obj"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["vertex_count"] > 0
    assert data["face_count"] > 0
    assert "bounding_box" in data


def test_parse_fbx_returns_materials():
    resp = client.post("/api/v1/parse/fbx", files=_fake_file("scene.fbx"))
    assert resp.status_code == 200
    data = resp.json()
    assert "materials" in data
    assert isinstance(data["materials"], list)
