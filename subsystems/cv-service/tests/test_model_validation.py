from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_model_validate_returns_errors():
    resp = client.post(
        "/api/v1/detect/model-validate",
        json={"model_file_url": "s3://bucket/model.obj", "validation_type": "topology"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is False
    assert len(data["errors"]) >= 1


def test_model_validate_returns_warnings():
    resp = client.post(
        "/api/v1/detect/model-validate",
        json={"model_file_url": "s3://bucket/model.obj"},
    )
    data = resp.json()
    assert isinstance(data["warnings"], list)
    assert len(data["warnings"]) >= 1
