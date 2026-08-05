"""Focused tests for the governed ArcPy/DTS catalog bridge."""

import asyncio
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from data_agent import mcp_asset_bridge as bridge


def test_sanitized_evidence_has_no_remote_transport_identifiers():
    value = bridge._sanitize_for_storage(
        {
            "status": "succeeded",
            "id": "job-123",
            "job_id": "job-123",
            "artifact_id": "artifact-123",
            "signed_url": "https://example.invalid/signed",
            "dataset": {"feature_count": 5},
            "messages": ["completed"],
        }
    )
    assert value == {
        "status": "succeeded",
        "dataset": {"feature_count": 5},
        "messages": ["completed"],
    }
    serialized = json.dumps(value)
    assert "job-123" not in serialized
    assert "artifact-123" not in serialized
    assert "https://" not in serialized


def test_job_id_accepts_arcpy_queued_record_id():
    assert bridge._job_id({"id": "queued-job", "status": "queued"}) == "queued-job"
    assert bridge._job_id({"job_id": "explicit-job", "id": "other"}) == "explicit-job"


def test_job_failure_includes_stable_arcpy_error_code(monkeypatch):
    calls = []

    async def call(_server, tool, _args):
        calls.append(tool)
        if tool == "get_job":
            return {"id": "job", "status": "failed"}
        if tool == "get_job_log":
            return {"error_code": "WORKER_EXECUTION_FAILED", "result": []}
        raise AssertionError(tool)

    monkeypatch.setattr(bridge, "_call", call)
    with pytest.raises(bridge.McpAssetBridgeError, match="WORKER_EXECUTION_FAILED"):
        asyncio.run(bridge._poll("arcpy-mcp", "job", timeout=1))
    assert calls == ["get_job", "get_job_log"]


def test_result_artifact_accepts_arcpy_output_artifact_ids():
    assert bridge._result_artifact_id(
        {"result": {"output_artifact_ids": ["output-artifact"]}},
        "input-artifact",
    ) == "output-artifact"


@pytest.mark.parametrize(
    "prompt",
    [
        "请立即调用 run_mcp_asset_workflow，mcp_server=dts-mcp，asset_id=16",
        "用 DTS MCP 的 road 管道处理资产 16，DOM 资产 17，DEM 资产 18",
        "用 arcpy-mcp 投影资产ID: 7",
    ],
)
def test_governed_mcp_asset_prompt_routes_to_general_without_llm(prompt):
    from data_agent.intent_router import classify_intent

    intent, reason, tokens, categories, _language, mode = classify_intent(prompt)
    assert intent == "GENERAL"
    assert reason == "governed_mcp_asset_workflow"
    assert tokens == 0
    assert categories >= {"collaboration", "spatial_processing"}
    assert mode == "agentic"


def test_safe_zip_rejects_traversal_and_symlink(tmp_path: Path):
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../escape.txt", "bad")
    with pytest.raises(bridge.McpAssetBridgeError, match="路径穿越"):
        bridge._safe_extract_zip(traversal, tmp_path / "out")

    valid = tmp_path / "valid.zip"
    with zipfile.ZipFile(valid, "w") as archive:
        archive.writestr("nested/file.txt", "ok")
    files = bridge._safe_extract_zip(valid, tmp_path / "valid-out")
    assert files == [tmp_path / "valid-out" / "nested" / "file.txt"]


def test_dts_building_asset_requires_supporting_dom(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(bridge, "get_engine", lambda: None)
    result = asyncio.run(
        bridge.run_mcp_asset_workflow(
            asset_id=7,
            mcp_server="dts-mcp",
            operation="road",
        )
    )
    assert result["status"] == "error"
    assert result["code"] == "DTS_INPUT_REQUIRED"


def test_arcpy_workflow_calls_health_inspect_process_and_registers_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls = []
    input_path = tmp_path / "source.gpkg"
    input_path.write_bytes(b"source")
    output_bytes = b"processed-gpkg"
    output_sha = hashlib.sha256(output_bytes).hexdigest()
    upload_digest = {}

    monkeypatch.setattr(
        bridge,
        "_asset_row",
        lambda asset_id: {
            "id": asset_id,
            "asset_name": "buildings.gpkg",
            "technical_metadata": {"storage": {"path": str(input_path)}},
            "business_metadata": {},
            "operational_metadata": {},
            "lineage_metadata": {},
            "owner_username": "tester",
            "is_shared": True,
        },
    )
    monkeypatch.setattr(bridge, "get_engine", lambda: None)
    monkeypatch.setattr(bridge, "_copy_or_export_asset", lambda *args, **kwargs: input_path)
    monkeypatch.setattr(bridge, "_signed_put", lambda *args, **kwargs: None)

    def write_result(_url, path, _ca_cert):
        Path(path).write_bytes(output_bytes)

    monkeypatch.setattr(bridge, "_signed_download", write_result)
    registered = {}

    def register(**kwargs):
        registered.update(kwargs)
        return 88

    monkeypatch.setattr(bridge, "_register_output", register)

    async def call(_server, tool, args):
        calls.append((tool, args))
        if tool == "health_check":
            return {"status": "healthy"}
        if tool == "get_capabilities":
            return {"product": "ArcGIS Pro"}
        if tool == "create_upload":
            upload_digest["sha256"] = args["expected_sha256"]
            return {"artifact_id": "input-artifact", "upload_url": "https://upload"}
        if tool == "complete_upload":
            return {"state": "ready", "actual_sha256": upload_digest["sha256"]}
        if tool == "inspect_dataset":
            return {"job_id": "inspect-job"}
        if tool == "project_features":
            return {"job_id": "process-job"}
        if tool == "get_job":
            job_id = args["job_id"]
            if job_id == "inspect-job":
                return {"status": "succeeded", "job_id": job_id, "dataset": {"feature_count": 2}}
            return {
                "status": "succeeded",
                "job_id": job_id,
                "result_artifacts": [{"artifact_id": "output-artifact"}],
            }
        if tool == "create_download":
            return {
                "download_url": "https://download",
                "actual_sha256": output_sha,
                "logical_name": "projected.gpkg",
            }
        raise AssertionError(f"unexpected MCP tool: {tool}")

    monkeypatch.setattr(bridge, "_call", call)
    result = asyncio.run(
        bridge._run_arcpy(
            7,
            "project_features",
            {"feature_limit": 5000, "output_spatial_reference": 32640},
            bridge.uuid.uuid4(),
            "tester",
            None,
        )
    )

    assert result["status"] == "succeeded"
    assert result["output_asset_id"] == 88
    assert registered["output_path"].name == "projected.gpkg"
    assert [name for name, _args in calls] == [
        "health_check",
        "get_capabilities",
        "create_upload",
        "complete_upload",
        "inspect_dataset",
        "get_job",
        "project_features",
        "get_job",
        "create_download",
    ]
    assert calls[2][1]["expected_sha256"]


def test_dts_road_contract_rejects_missing_sidecars(tmp_path: Path):
    source = tmp_path / "roads.shp"
    source.write_bytes(b"not-a-real-shapefile")
    with pytest.raises(bridge.McpAssetBridgeError) as error:
        bridge._prepare_road_shapefile(source, tmp_path, None)
    assert error.value.code == "DTS_ROAD_SIDECAR_MISSING"
