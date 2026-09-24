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
from data_agent.hydro_workbench.coordinator import (
    HydroRunAccessError,
    HydroRunCoordinator,
    HydroRunStateError,
)
from data_agent.hydro_workbench.k8s_api import job_manifest
from data_agent.hydro_workbench.storage import read_manifest, read_status
from data_agent.user_context import current_user_id


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


@pytest.fixture(autouse=True)
def development_fixture_switch(monkeypatch):
    monkeypatch.setenv("HYDRO_ALLOW_DEVELOPMENT_FIXTURES", "true")


def test_manifest_separates_aoi_model_domain_and_display_extent():
    manifest = build_run_manifest(request(domain_buffer_m=1_000))
    area = manifest["area"]
    assert area["user_aoi"]["bbox"] == area["result_display_extent"]["bbox"]
    assert area["model_calculation_domain"]["bbox"][0] < area["user_aoi"]["bbox"][0]
    assert area["model_calculation_domain"]["bbox"][2] > area["user_aoi"]["bbox"][2]
    assert manifest["immutability"]["state"] == "frozen"
    assert len(manifest["immutability"]["sha256"]) == 64


def test_manifest_discloses_defaults_and_fixture_sources():
    manifest = build_run_manifest(
        {"aoi": [54.35, 24.35, 54.45, 24.45], "input_mode": "development_fixture"}
    )
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
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert job["spec"]["template"]["spec"]["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    assert any(volume["name"] == "tmp" for volume in job["spec"]["template"]["spec"]["volumes"])
    assert job["spec"]["activeDeadlineSeconds"] == manifest["runtime"]["active_deadline_seconds"]
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


def test_customer_mode_is_the_safe_default_and_requires_model_inputs():
    with pytest.raises(ManifestValidationError, match="customer_mount requires a URI"):
        build_run_manifest({"aoi": [54.35, 24.35, 54.45, 24.45]})


@pytest.mark.parametrize(
    "field,value",
    [
        ("rainfall_pattern", "unsupported"),
        ("one_d_routing_method", "unsupported"),
        ("one_d_infiltration_method", "unsupported"),
    ],
)
def test_model_enum_parameters_are_rejected(field, value):
    with pytest.raises(ManifestValidationError) as raised:
        build_run_manifest(request(**{field: value}))
    assert field in {issue["field"] for issue in raised.value.issues}


def test_customer_source_uri_scheme_is_validated():
    with pytest.raises(ManifestValidationError) as raised:
        build_run_manifest(
            request(
                input_mode="customer_mount",
                data_sources={"network": {"uri": "not-a-uri"}, "terrain": {"uri": "nas://dtm"}},
            )
        )
    assert "data_sources.network.uri" in {issue["field"] for issue in raised.value.issues}


@pytest.mark.parametrize(
    "uri",
    [
        "https://example.test/model.inp?X-Amz-Signature=secret",
        "s3://user:password@example-bucket/model.inp",
    ],
)
def test_customer_source_uri_cannot_embed_credentials_or_query_secrets(uri):
    with pytest.raises(ManifestValidationError) as raised:
        build_run_manifest(
            request(
                input_mode="customer_mount",
                data_sources={"network": {"uri": uri}, "terrain": {"uri": "nas://dtm"}},
            )
        )
    assert "data_sources.network.uri" in {issue["field"] for issue in raised.value.issues}


def test_two_d_grid_request_is_bounded_before_submission(monkeypatch):
    monkeypatch.setenv("HYDRO_MAX_TWO_D_CELLS", "100000")
    with pytest.raises(ManifestValidationError) as raised:
        build_run_manifest(request(model_type="two_d", two_d_grid_resolution_m=0.5))
    assert "aoi" in {issue["field"] for issue in raised.value.issues}


def test_development_fixture_execution_requires_explicit_environment_switch(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("HYDRO_ALLOW_DEVELOPMENT_FIXTURES", "false")
    coordinator = HydroRunCoordinator(root=tmp_path, k8s_client=FakeKubernetes())
    with pytest.raises(ManifestValidationError, match="development fixtures are disabled"):
        coordinator.submit(request(model_type="one_d"))
    assert list(tmp_path.iterdir()) == []


def test_run_access_is_scoped_to_authenticated_owner(tmp_path: Path):
    client = FakeKubernetes()
    alice = current_user_id.set("alice")
    try:
        coordinator = HydroRunCoordinator(root=tmp_path, k8s_client=client)
        run_id = coordinator.submit(request(model_type="one_d"))["run_id"]
    finally:
        current_user_id.reset(alice)
    bob = current_user_id.set("bob")
    try:
        with pytest.raises(HydroRunAccessError):
            coordinator.status(run_id)
    finally:
        current_user_id.reset(bob)


class SucceededKubernetes(FakeKubernetes):
    def get_job(self, name):
        return {"metadata": {"name": name}, "status": {"succeeded": 1}}


def test_job_success_without_result_is_not_reported_as_completed(tmp_path: Path):
    coordinator = HydroRunCoordinator(root=tmp_path, k8s_client=SucceededKubernetes())
    run_id = coordinator.submit(request(model_type="one_d"))["run_id"]
    response = coordinator.status(run_id)
    assert response["status"]["status"] == "failed"
    assert response["status"]["error"] == "result_missing_after_job_success"


def test_completed_run_cannot_be_cancelled(tmp_path: Path):
    coordinator = HydroRunCoordinator(root=tmp_path, k8s_client=FakeKubernetes())
    run_id = coordinator.submit(request(model_type="one_d"))["run_id"]
    from data_agent.hydro_workbench.storage import update_status

    update_status(run_id, "completed", progress=100, root=tmp_path)
    with pytest.raises(HydroRunStateError, match="run_not_cancellable"):
        coordinator.cancel(run_id)


def test_preflight_only_reports_active_model_parameters():
    report = build_preflight(request(model_type="one_d"))
    keys = {parameter["key"] for parameter in report["parameter_readiness"]}
    assert "one_d.routing_method" in keys
    assert "two_d.grid_resolution_m" not in keys
    assert "coupling.mode" not in keys


def test_preflight_matches_development_fixture_execution_gate(monkeypatch):
    monkeypatch.setenv("HYDRO_ALLOW_DEVELOPMENT_FIXTURES", "false")
    report = build_preflight(request(model_type="one_d"))
    assert report["status"] == "blocked"
    assert report["can_submit"] is False
    assert report["resource_estimate"]["development_fixture_enabled"] is False
    assert any(check["key"] == "development_fixture_gate" for check in report["checks"])


def test_preflight_matches_gpu_execution_gate(monkeypatch):
    monkeypatch.setenv("HYDRO_GPU_ENABLED", "false")
    report = build_preflight(request(model_type="one_d", resource_profile="gpu"))
    assert report["status"] == "blocked"
    assert report["can_submit"] is False
    resource_check = next(check for check in report["checks"] if check["key"] == "runtime_resources")
    assert resource_check["status"] == "blocked"
