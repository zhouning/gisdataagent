from __future__ import annotations

import hashlib
import io
import json
import zipfile

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


def test_browser_filegdb_zip_can_continue_from_finalize_to_ingest(tmp_path, monkeypatch):
    monkeypatch.setenv("GDA_OFFLINE_INGEST_AUTH_REQUIRED", "false")
    monkeypatch.setenv("GDA_FILE_LAKE_ROOT", str(tmp_path / "lake"))
    payload_buffer = io.BytesIO()
    with zipfile.ZipFile(payload_buffer, "w") as archive:
        archive.writestr("delivery/DLTB.gdb/a00000001.gdbtable", b"fixture")
    payload = payload_buffer.getvalue()
    client = TestClient(Starlette(routes=get_offline_ingest_routes()))
    created = client.post(
        "/api/offline-ingest/sessions",
        json={
            "filename": "DLTB.gdb.zip",
            "size": len(payload),
            "chunk_size": 1024 * 1024,
            "asset_kind": "filegdb_bundle",
        },
    ).json()
    session_id = created["session_id"]
    assert client.put(
        f"/api/offline-ingest/sessions/{session_id}/chunks/0",
        content=payload,
        headers={"x-chunk-sha256": hashlib.sha256(payload).hexdigest()},
    ).status_code == 200
    assert client.post(f"/api/offline-ingest/sessions/{session_id}/finalize").status_code == 200

    response = client.post(
        f"/api/offline-ingest/sessions/{session_id}/ingest",
        json={"run_quality": False},
    )

    assert response.status_code == 202
    result = response.json()
    assert result["archive_expansion"]["gdb_paths"] == ["delivery/DLTB.gdb"]
    assert result["run"]["assets"][0]["kind"] == "filegdb_bundle"
    repeated = client.post(
        f"/api/offline-ingest/sessions/{session_id}/ingest",
        json={"run_quality": False},
    )
    assert repeated.status_code == 200
    assert repeated.json()["resumed"] is True


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


def test_offline_semantic_catalog_is_available_without_database(tmp_path, monkeypatch):
    monkeypatch.setenv("GDA_OFFLINE_INGEST_AUTH_REQUIRED", "false")
    monkeypatch.setenv("GDA_FILE_LAKE_ROOT", str(tmp_path / "lake"))
    app = Starlette(routes=get_offline_ingest_routes())
    response = TestClient(app).get("/api/offline-ingest/semantic-catalog")
    assert response.status_code == 200
    assert response.json()["sources"] == []


def test_semantic_project_route_returns_projection(monkeypatch):
    monkeypatch.setenv("GDA_OFFLINE_INGEST_AUTH_REQUIRED", "false")
    from data_agent.dltb_vertical_demo import DLTBVerticalDemo
    captured = {}

    def fake_build(self, plan_id, **kwargs):
        captured.update(kwargs)
        return {
            "status": "succeeded",
            "projection": {
                "projection_id": "a" * 32,
                "semantic_source": "land_parcel_current",
                "production_eligible": False,
            },
            "metrics": {"feature_count": 0},
        }

    monkeypatch.setattr(DLTBVerticalDemo, "build_projection", fake_build)
    app = Starlette(routes=get_offline_ingest_routes())
    response = TestClient(app).post(
        "/api/offline-ingest/standardization/" + "b" * 32 + "/semantic-project",
        json={"mode": "rehearsal"},
    )
    assert response.status_code == 200
    assert response.json()["projection"]["semantic_source"] == "land_parcel_current"
    assert captured["publish_postgis"] is True
    assert captured["postgis_table_name"] == "land_parcel_current"
