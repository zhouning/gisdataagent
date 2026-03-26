from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_compare_coordinates_returns_rmse():
    resp = client.post("/api/v1/compare/coordinates", json={
        "pairs": [
            {"source_x": 121.4737, "source_y": 31.2304, "target_x": 121.4738, "target_y": 31.2305},
            {"source_x": 118.7969, "source_y": 32.0603, "target_x": 118.7970, "target_y": 32.0604},
        ],
        "source_datum": "WGS84",
        "target_datum": "CGCS2000",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["pair_count"] == 2
    assert data["rmse_m"] > 0
    assert data["mean_error_m"] > 0


def test_compare_empty_pairs():
    resp = client.post("/api/v1/compare/coordinates", json={
        "pairs": [],
        "source_datum": "WGS84",
        "target_datum": "CGCS2000",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["pair_count"] == 0
