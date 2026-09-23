"""Contract and orchestration tests for the hydro workbench MVP."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_agent.hydro_workbench.contracts import (
    ManifestValidationError,
    build_preflight,
    build_run_manifest,
)
from data_agent.hydro_workbench.coordinator import HydroRunCoordinator
from data_agent.hydro_workbench.k8s_api import job_manifest
from data_agent.hydro_workbench.storage import read_manifest, read_status


def request(**overrides):
    payload = {
        "model_type": "coupled_1d_2d",
        "input_mode": "development_fixture",
        "resource_profile": "cpu_small",
        "aoi": [54.35, 24.35, 54.45, 24.45],
        "rainfall_total_mm": 50,
        "rainfall_duration_minutes": 60,
    }
    payload.update(overrides)
    return payload


def test_manifest_separates_aoi_model_domain_and_display_extent():
    manifest = build_run_manifest(request(domain_buffer_m=1_000))
    area = manifest["area"]
    assert area["user_aoi"]["bbox"] == area["result_display_extent"]["bbox"]
    assert area["model_calculation_domain"]["bbox"][0] < area["user_aoi"]["bbox"][0]
    assert area["model_calculation_domain"]["bbox"][2] > area["user_aoi"]["bbox"][2]
    assert manifest["immutability"]["state"] == "frozen"
    assert len(manifest["immutability"]["sha256"]) == 64


def test_manifest_discloses_defaults_and_fixture_sources():
    manifest = build_run_manifest({"aoi": [54.35, 24.35, 54.45, 24.45]})
    assert manifest["parameter_provenance"]["rainfall.total_mm"] == "system_default"
    assert manifest["data_sources"]["network"]["status"] == "development_fixture"
    assert manifest["data_sources"]["terrain"]["provided_by_customer"] is False


@pytest.mark.parametrize(
    "payload,field",
    [
        ({"aoi": [54.4, 24.4, 54.3, 24.5]}, "aoi"),
        (request(rainfall_total_mm=-1), "rainfall_total_mm"),
        (request(resource_profile="unbounded"), "resource_profile"),
        (request(input_mode="customer_mount"), "data_sources.network"),
    ],
)
def test_invalid_manifest_is_rejected(payload, field):
    with pytest.raises(ManifestValidationError) as raised:
        build_run_manifest(payload)
    assert field in {issue["field"] for issue in raised.value.issues}


def test_job_manifest_uses_pvc_and_cpu_profile():
    manifest = build_run_manifest(request(model_type="one_d"))
    job = job_manifest(
        manifest,
        image="hydro:test",
        namespace="hydro-dev",
        pvc_name="hydro-runs",
    )
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert container["command"][-1] == manifest["run_id"]
    assert container["resources"]["limits"]["cpu"] == "2"
    assert "nvidia.com/gpu" not in container["resources"]["limits"]
    assert job["metadata"]["namespace"] == "hydro-dev"


class FakeKubernetes:
    def __init__(self):
        self.created = None

    def create_job(self, job):
        self.created = job
        return {"metadata": {"uid": "job-uid-1"}}

    def get_job(self, name):
        return {"metadata": {"name": name}, "status": {"active": 1}}

    def delete_job(self, name):
        return {"metadata": {"name": name}}

    def list_pods_for_job(self, name):
        return {"items": [{"metadata": {"name": f"{name}-pod"}}]}

    def get_pod_logs(self, name):
        return f"completed:{name}"


def test_coordinator_freezes_manifest_before_submitting_job(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HYDRO_GPU_ENABLED", "false")
    client = FakeKubernetes()
    coordinator = HydroRunCoordinator(root=tmp_path, k8s_client=client)
    submitted = coordinator.submit(request(model_type="one_d"))
    run_id = submitted["run_id"]
    assert client.created["metadata"]["labels"]["hydro.gisdataagent.io/run-id"] == run_id
    assert read_manifest(run_id, tmp_path)["run_id"] == run_id
    assert read_status(run_id, tmp_path)["status"] == "queued"


def test_gpu_profile_is_fail_closed_when_environment_has_no_gpu(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HYDRO_GPU_ENABLED", "false")
    coordinator = HydroRunCoordinator(root=tmp_path, k8s_client=FakeKubernetes())
    with pytest.raises(ManifestValidationError, match="GPU profile is disabled"):
        coordinator.submit(request(resource_profile="gpu"))
    assert list(tmp_path.iterdir()) == []


def test_customer_mount_is_fail_closed_until_etl_adapter_exists(tmp_path: Path):
    coordinator = HydroRunCoordinator(root=tmp_path, k8s_client=FakeKubernetes())
    payload = request(
        input_mode="customer_mount",
        data_sources={
            "network": {"uri": "nas://hydro/model.inp"},
            "terrain": {"uri": "nas://hydro/terrain.npz"},
        },
    )
    with pytest.raises(ManifestValidationError, match="customer data execution is fail-closed"):
        coordinator.submit(payload)
    assert list(tmp_path.iterdir()) == []


def test_coordinator_exposes_bounded_job_logs(tmp_path: Path):
    client = FakeKubernetes()
    coordinator = HydroRunCoordinator(root=tmp_path, k8s_client=client)
    run_id = coordinator.submit(request(model_type="one_d"))["run_id"]
    logs = coordinator.logs(run_id)
    assert logs["status"] == "available"
    assert logs["pod_name"].endswith("-pod")
    assert logs["logs"].startswith("completed:")


def test_manifest_is_json_serialisable():
    encoded = json.dumps(build_run_manifest(request()), sort_keys=True)
    assert "hydro_run_manifest.v1" in encoded


def test_preflight_is_non_mutating_and_blocks_customer_etl_gap():
    fixture = build_preflight(request(model_type="two_d"))
    assert fixture["status"] == "ready"
    assert fixture["can_submit"] is True
    assert fixture["required_sources"][0]["status"] == "ready"

    customer = build_preflight(
        request(
            model_type="one_d",
            input_mode="customer_mount",
            data_sources={"network": {"uri": "nas://hydro/normalized/model.inp"}},
        )
    )
    assert customer["status"] == "blocked"
    assert customer["can_submit"] is False
    assert customer["checks"][-1]["key"] == "customer_etl"


def test_preflight_reports_missing_customer_uris_without_throwing():
    report = build_preflight(request(model_type="coupled_1d_2d", input_mode="customer_mount"))
    assert report["status"] == "blocked"
    assert report["can_submit"] is False
    assert {source["detail"] for source in report["required_sources"]} == {"URI required"}
