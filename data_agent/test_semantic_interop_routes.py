"""HTTP contract tests for the semantic-workspace standards controls."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from starlette.applications import Starlette
from starlette.testclient import TestClient

from data_agent.api import semantic_interop_routes as routes


class _User:
    identifier = "interop-tester"
    metadata = {"role": "admin", "tenant_id": "test"}


def _app(monkeypatch, tmp_path: Path, payloads: dict[str, Path]) -> Starlette:
    monkeypatch.setattr(routes, "_get_user_from_request", lambda _request: _User())
    monkeypatch.setattr(routes, "_IMPORT_ROOT", tmp_path / "imports")
    monkeypatch.setattr(routes, "_artifact", lambda scope, kind: payloads[(scope, kind)])
    return Starlette(routes=routes.get_semantic_interop_routes())


def _semantic_payload() -> dict:
    return {
        "schema": "gda.multilingual-virtual-semantic-layer.v1",
        "semantic_version": "test-v1",
        "source_binding": {"source_id": 13, "database_name": "makani_sync_full"},
        "semantic_assets": [
            {
                "asset_id": "makani.facilities",
                "labels": {"en": "facilities"},
                "physical_tables": ["public.facilities"],
                "fields": [
                    {
                        "semantic_field": "facility_id",
                        "physical_field": "facility_id",
                        "labels": {"en": "facility id"},
                        "business_role": "identifier",
                        "technical_metadata": {"data_type": "integer", "nullable": False},
                    }
                ],
            }
        ],
        "table_bindings": [],
        "relationships": [],
        "metric_contracts": [],
    }


def _ontology_payload() -> dict:
    return {
        "schema": "gda.ontology-runtime-overlay.v1",
        "ontology_enrichment_version": "test-v1",
        "source_evidence": {"source_id": 12},
        "concepts": [
            {
                "concept_id": "facility",
                "labels": {"en": "facility"},
                "physical_binding": "public.facilities",
                "fields": [],
            }
        ],
        "relations": [],
    }


def test_export_endpoint_returns_ossie_document(monkeypatch, tmp_path):
    semantic_path = tmp_path / "semantic.json"
    semantic_path.write_text(json.dumps(_semantic_payload()), encoding="utf-8")
    client = TestClient(_app(monkeypatch, tmp_path, {("makani", "semantic-layer"): semantic_path}))

    response = client.get("/api/semantic/interop/export/semantic-layer/makani/ossie-yaml")

    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('"makani-semantic-layer.ossie.yaml"')
    document = yaml.safe_load(response.text)
    assert document["version"] == "0.2.0.dev0"
    assert document["semantic_model"][0]["datasets"][0]["source"] == "public.facilities"


def test_sources_endpoint_returns_registered_current_bundles(monkeypatch, tmp_path):
    monkeypatch.setattr(
        routes,
        "current_artifact_manifest",
        lambda scope: {
            "bundle_id": f"{scope}-bundle",
            "source": {"database_name": f"{scope}_db"},
        },
    )
    client = TestClient(_app(monkeypatch, tmp_path, {}))

    response = client.get("/api/semantic/interop/sources")

    assert response.status_code == 200
    assert {item["key"] for item in response.json()["items"]} == {"liveability", "makani"}
    assert response.json()["items"][0]["database_name"]


def test_ontology_export_endpoint_supports_json(monkeypatch, tmp_path):
    ontology_path = tmp_path / "ontology.json"
    ontology_path.write_text(json.dumps(_ontology_payload()), encoding="utf-8")
    client = TestClient(_app(monkeypatch, tmp_path, {("liveability", "ontology"): ontology_path}))

    response = client.get("/api/semantic/interop/export/ontology/liveability/json")

    assert response.status_code == 200
    assert json.loads(response.text)["schema"] == "gda.ontology-runtime-overlay.v1"


def test_external_import_is_staged_non_executable(monkeypatch, tmp_path):
    client = TestClient(_app(monkeypatch, tmp_path, {}))
    ossie = {
        "version": "0.2.0.dev0",
        "semantic_model": [
            {
                "name": "external",
                "datasets": [{"name": "facilities", "source": "public.facilities", "fields": []}],
            }
        ],
    }

    response = client.post(
        "/api/semantic/interop/import",
        data={
            "source": "makani",
            "kind": "semantic-layer",
            "format": "ossie-yaml",
            "mode": "projection-only",
        },
        files={
            "file": ("external.yaml", yaml.safe_dump(ossie, sort_keys=False), "application/yaml")
        },
    )

    assert response.status_code == 201
    stage = response.json()["stage"]
    assert stage["status"] == "staged_non_executable"
    assert stage["execution_authority"] is False
    assert stage["summary"]["dataset_count"] == 1
    assert list((tmp_path / "imports").glob("*.manifest.json"))


def test_runtime_import_is_forced_non_executable(monkeypatch, tmp_path):
    client = TestClient(_app(monkeypatch, tmp_path, {}))
    payload = _semantic_payload()
    payload["status"] = "active"
    payload["runtime_role"] = {"execution_authority": True}
    payload["semantic_assets"][0]["execution_eligible"] = True

    response = client.post(
        "/api/semantic/interop/import",
        data={
            "source": "makani",
            "kind": "semantic-layer",
            "format": "json",
            "mode": "strict",
        },
        files={"file": ("runtime.json", json.dumps(payload), "application/json")},
    )

    assert response.status_code == 201
    stage = response.json()["stage"]
    staged_path = tmp_path / "imports" / f"{stage['stage_id']}.semantic_layer.json"
    staged = json.loads(staged_path.read_text())
    assert staged["status"] == "projection_only_import_requires_review"
    assert staged["runtime_role"]["execution_authority"] is False
    assert staged["semantic_assets"][0]["execution_eligible"] is False


def test_import_rejects_source_binding_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr(
        routes,
        "current_artifact_manifest",
        lambda _scope: {"source": {"database_name": "makani_sync_full"}},
    )
    client = TestClient(_app(monkeypatch, tmp_path, {}))
    payload = _semantic_payload()
    payload["source_binding"] = {"database_name": "other_database"}

    response = client.post(
        "/api/semantic/interop/import",
        data={"source": "makani", "kind": "semantic-layer", "format": "json", "mode": "strict"},
        files={"file": ("runtime.json", json.dumps(payload), "application/json")},
    )

    assert response.status_code == 400
    assert "source binding mismatch" in response.json()["error"]


def test_plain_ossie_strict_import_is_rejected(monkeypatch, tmp_path):
    client = TestClient(_app(monkeypatch, tmp_path, {}))
    ossie = {
        "version": "0.2.0.dev0",
        "semantic_model": [
            {"name": "external", "datasets": [{"name": "t", "source": "public.t", "fields": []}]}
        ],
    }
    response = client.post(
        "/api/semantic/interop/import",
        data={
            "source": "liveability",
            "kind": "semantic-layer",
            "format": "ossie-yaml",
            "mode": "strict",
        },
        files={
            "file": ("external.yaml", yaml.safe_dump(ossie, sort_keys=False), "application/yaml")
        },
    )
    assert response.status_code == 400
    assert "strict OSSIE import" in response.json()["error"]
