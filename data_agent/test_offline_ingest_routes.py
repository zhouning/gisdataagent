from __future__ import annotations

import hashlib
import json

from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api.offline_ingest_routes import get_offline_ingest_routes


def test_resumable_http_contract_without_chainlit_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("GDA_OFFLINE_INGEST_AUTH_REQUIRED", "false")
    monkeypatch.setenv("GDA_FILE_LAKE_ROOT", str(tmp_path / "lake"))
    app = Starlette(routes=get_offline_ingest_routes())
    client = TestClient(app)
    payload = b"small test payload"
    response = client.post(
        "/api/offline-ingest/sessions",
        json={
            "filename": "sample.tif",
            "size": len(payload),
            "chunk_size": 1024 * 1024,
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
    )
    assert response.status_code == 201
    session_id = response.json()["session_id"]
    response = client.put(
        f"/api/offline-ingest/sessions/{session_id}/chunks/0",
        data=payload,
        headers={"x-chunk-sha256": hashlib.sha256(payload).hexdigest()},
    )
    assert response.status_code == 200
    response = client.post(f"/api/offline-ingest/sessions/{session_id}/finalize")
    assert response.status_code == 200
    assert response.json()["asset"]["kind"] == "raster"


def test_contract_catalog_reports_unconfigured_state(monkeypatch):
    monkeypatch.setenv("GDA_OFFLINE_INGEST_AUTH_REQUIRED", "false")
    monkeypatch.delenv("GDA_STANDARD_CONTRACT_XLSX", raising=False)
    monkeypatch.delenv("GDA_STANDARD_CONTRACTS", raising=False)
    app = Starlette(routes=get_offline_ingest_routes())
    response = TestClient(app).get("/api/offline-ingest/contracts")
    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"


def test_versioned_json_contract_precedes_workbook_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("GDA_OFFLINE_INGEST_AUTH_REQUIRED", "false")
    json_path = tmp_path / "contract.json"
    json_path.write_text(
        json.dumps(
            {
                "schema_version": "gda.standard-contract-catalog.v2",
                "contract_id": "reviewed-json",
                "authority": "ea_analysis_candidate",
                "contracts": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GDA_STANDARD_CONTRACTS", str(json_path))
    monkeypatch.setenv("GDA_STANDARD_CONTRACT_XLSX", str(tmp_path / "discovery.xlsx"))
    app = Starlette(routes=get_offline_ingest_routes())
    response = TestClient(app).get("/api/offline-ingest/contracts")
    assert response.status_code == 200
    assert response.json()["contract_id"] == "reviewed-json"


def test_overview_and_run_list_are_available_for_operations_console(tmp_path, monkeypatch):
    monkeypatch.setenv("GDA_OFFLINE_INGEST_AUTH_REQUIRED", "false")
    monkeypatch.setenv("GDA_FILE_LAKE_ROOT", str(tmp_path / "lake"))
    app = Starlette(routes=get_offline_ingest_routes())
    client = TestClient(app)
    response = client.get("/api/offline-ingest/overview")
    assert response.status_code == 200
    assert response.json()["schema"] == "gda.offline-ingest-overview.v1"
    response = client.get("/api/offline-ingest/runs?limit=5")
    assert response.status_code == 200
    assert response.json()["runs"] == []
