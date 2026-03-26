import io
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _fake_file(name: str = "raster.tif") -> dict:
    return {"file": (name, io.BytesIO(b"\x00\x00 fake raster"), "image/tiff")}


def test_raster_quality_returns_score():
    resp = client.post("/api/v1/detect/raster-quality", files=_fake_file())
    assert resp.status_code == 200
    data = resp.json()
    assert "quality_score" in data
    assert 0.0 <= data["quality_score"] <= 1.0


def test_raster_quality_returns_issues_and_metrics():
    resp = client.post("/api/v1/detect/raster-quality", files=_fake_file())
    data = resp.json()
    assert isinstance(data["issues"], list)
    assert len(data["issues"]) >= 1
    assert "resolution_dpi" in data["metrics"]
