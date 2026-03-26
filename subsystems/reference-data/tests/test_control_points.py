from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_nearby_points_returns_list():
    resp = client.get("/api/v1/points/nearby", params={"longitude": 121.47, "latitude": 31.23})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "point_id" in data[0]
    assert "longitude" in data[0]


def test_nearby_points_respects_limit():
    resp = client.get("/api/v1/points/nearby", params={"longitude": 121.47, "latitude": 31.23, "limit": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) <= 1


def test_get_point_by_id():
    resp = client.get("/api/v1/points/CP-SH-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["point_id"] == "CP-SH-001"
    assert data["datum"] == "CGCS2000"
