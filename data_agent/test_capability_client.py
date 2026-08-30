from __future__ import annotations

import json

import httpx
import pytest

from data_agent.capability_client import (
    CAPABILITY_FINGERPRINT_HEADER,
    CapabilityClient,
    CapabilityClientConfigurationError,
    CapabilityContractDriftError,
    CapabilityInvocationError,
    CapabilityRemoteProtocolError,
    normalize_platform_base_url,
    project_capability_http_request,
)
from data_agent.capability_registry import (
    CAPABILITY_REGISTRY_SCHEMA,
    CATALOG_ASSET_SEARCH,
    DATAOPS_RUN_CANCEL,
    CapabilityOutputError,
    CapabilitySpec,
)


def _detail(spec, *, fingerprint: str | None = None) -> dict:
    return {
        "spec": spec.model_dump(mode="json", by_alias=True),
        "fingerprint": fingerprint or spec.fingerprint,
        "projections": {},
    }


def _client(handler) -> CapabilityClient:
    return CapabilityClient(
        base_url="https://platform.example.test",
        access_token="test-session-token",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.parametrize(
    "value",
    (
        "file:///tmp/platform",
        "https://user:secret@platform.example.test",
        "https://platform.example.test/base",
        "https://platform.example.test?tenant=spoofed",
    ),
)
def test_platform_url_rejects_unsafe_or_ambiguous_forms(value: str) -> None:
    with pytest.raises(CapabilityClientConfigurationError):
        normalize_platform_base_url(value)


def test_client_requires_authenticated_token(monkeypatch) -> None:
    monkeypatch.delenv("GDA_ACCESS_TOKEN", raising=False)
    with pytest.raises(CapabilityClientConfigurationError, match="access token"):
        CapabilityClient(base_url="https://platform.example.test")


def test_authenticated_manifest_discovery_preserves_runtime_filters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "schema": CAPABILITY_REGISTRY_SCHEMA,
                "fingerprint": "a" * 64,
                "llm_mode": "disabled",
                "surface": "cli",
                "count": 0,
                "capabilities": [],
            },
        )

    with _client(handler) as client:
        manifest = client.list_capabilities(
            surface="cli",
            llm_mode="disabled",
        )

    assert manifest["schema"] == CAPABILITY_REGISTRY_SCHEMA
    assert len(requests) == 1
    assert requests[0].url.path == "/api/capability-specs"
    assert dict(requests[0].url.params) == {
        "surface": "cli",
        "llm_mode": "disabled",
    }
    assert requests[0].headers["cookie"] == "access_token=test-session-token"


def test_catalog_invocation_validates_drift_and_uses_query_alias() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.startswith("/api/capability-specs/"):
            return httpx.Response(200, json=_detail(CATALOG_ASSET_SEARCH))
        return httpx.Response(
            200,
            headers={"x-request-id": "catalog-request-1"},
            json={
                "status": "success",
                "message": "Found 0 assets",
                "count": 0,
                "assets": [],
            },
        )

    with _client(handler) as client:
        result = client.invoke("catalog.asset.search", {"query": "roads"})

    assert len(requests) == 2
    detail_request, invoke_request = requests
    assert detail_request.url.params["version"] == "1.0.0"
    assert invoke_request.url.path == "/api/catalog/search"
    assert dict(invoke_request.url.params) == {"q": "roads"}
    assert invoke_request.headers[CAPABILITY_FINGERPRINT_HEADER] == (
        CATALOG_ASSET_SEARCH.fingerprint
    )
    assert result.data["assets"] == []
    assert result.request_id == "catalog-request-1"
    assert result.created is None


def test_cancel_projection_splits_path_identity_from_body() -> None:
    payload = {
        "run_id": "30000000-0000-4000-8000-000000000040",
        "client_request_id": "cancel-cli-20260805-001",
        "expected_state_version": 2,
        "reason": "operator cancelled an obsolete source refresh",
    }
    DATAOPS_RUN_CANCEL.validate_input(payload)

    projected = project_capability_http_request(DATAOPS_RUN_CANCEL, payload)

    assert projected.method == "POST"
    assert projected.path == (
        "/api/platform/v1/runs/"
        "30000000-0000-4000-8000-000000000040/cancel"
    )
    assert projected.query == {}
    assert projected.body == {
        "client_request_id": "cancel-cli-20260805-001",
        "expected_state_version": 2,
        "reason": "operator cancelled an obsolete source refresh",
    }
    assert "run_id" not in projected.body


@pytest.mark.parametrize(("status_code", "created"), ((202, True), (200, False)))
def test_cancel_invocation_accepts_admission_and_idempotent_replay(
    monkeypatch,
    status_code: int,
    created: bool,
) -> None:
    requests: list[httpx.Request] = []
    payload = {
        "run_id": "30000000-0000-4000-8000-000000000040",
        "client_request_id": "cancel-cli-20260805-001",
        "expected_state_version": 2,
        "reason": "operator cancelled an obsolete source refresh",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.startswith("/api/capability-specs/"):
            return httpx.Response(200, json=_detail(DATAOPS_RUN_CANCEL))
        return httpx.Response(
            status_code,
            json={
                "data": {"admission": "accepted"},
                "error": None,
                "request_id": "cancel-request-1",
                "created": created,
            },
        )

    monkeypatch.setattr(
        CapabilitySpec,
        "validate_output",
        lambda _spec, output: output,
    )
    with _client(handler) as client:
        result = client.invoke("dataops.run.cancel", payload)

    assert len(requests) == 2
    invoke_request = requests[1]
    assert invoke_request.url.path.endswith(
        "/30000000-0000-4000-8000-000000000040/cancel"
    )
    assert json.loads(invoke_request.content) == {
        "client_request_id": "cancel-cli-20260805-001",
        "expected_state_version": 2,
        "reason": "operator cancelled an obsolete source refresh",
    }
    assert result.status_code == status_code
    assert result.request_id == "cancel-request-1"
    assert result.created is created
    assert result.data == {"admission": "accepted"}


def test_platform_envelope_missing_request_identity_fails_closed(
    monkeypatch,
) -> None:
    payload = {
        "run_id": "30000000-0000-4000-8000-000000000040",
        "client_request_id": "cancel-cli-20260805-001",
        "expected_state_version": 2,
        "reason": "operator cancelled an obsolete source refresh",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/capability-specs/"):
            return httpx.Response(200, json=_detail(DATAOPS_RUN_CANCEL))
        return httpx.Response(
            202,
            json={
                "data": {"admission": "accepted"},
                "error": None,
                "created": True,
            },
        )

    monkeypatch.setattr(
        CapabilitySpec,
        "validate_output",
        lambda _spec, output: output,
    )
    with _client(handler) as client:
        with pytest.raises(
            CapabilityRemoteProtocolError,
            match="capability envelope",
        ):
            client.invoke("dataops.run.cancel", payload)


def test_contract_drift_fails_before_command_is_sent() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_detail(CATALOG_ASSET_SEARCH, fingerprint="f" * 64),
        )

    with _client(handler) as client:
        with pytest.raises(CapabilityContractDriftError, match="contract drift"):
            client.invoke("catalog.asset.search", {"query": "roads"})

    assert len(requests) == 1


def test_execution_race_contract_mismatch_is_typed_as_drift() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.startswith("/api/capability-specs/"):
            return httpx.Response(200, json=_detail(CATALOG_ASSET_SEARCH))
        return httpx.Response(
            409,
            json={
                "error": {
                    "code": "capability_contract_mismatch",
                    "message": "Serving contract changed after discovery",
                }
            },
        )

    with _client(handler) as client:
        with pytest.raises(CapabilityContractDriftError, match="contract drift"):
            client.invoke("catalog.asset.search", {"query": "roads"})

    assert len(requests) == 2


def test_invalid_remote_output_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/api/capability-specs/"):
            return httpx.Response(200, json=_detail(CATALOG_ASSET_SEARCH))
        return httpx.Response(200, json={"message": "missing canonical status"})

    with _client(handler) as client:
        with pytest.raises(CapabilityOutputError):
            client.invoke("catalog.asset.search", {"query": "roads"})


def test_server_error_is_typed_without_exposing_session_cookie() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"error": {"code": "policy_denied", "message": "Not allowed"}},
        )

    with _client(handler) as client:
        with pytest.raises(CapabilityInvocationError) as exc_info:
            client.get_capability("catalog.asset.search")

    assert "Not allowed" in str(exc_info.value)
    assert "test-session-token" not in str(exc_info.value)


def test_discovery_rejects_non_object_json() -> None:
    with _client(lambda _request: httpx.Response(200, json=[])) as client:
        with pytest.raises(CapabilityRemoteProtocolError, match="JSON object"):
            client.list_capabilities()


def test_projection_is_json_serializable_for_notebook_receipts() -> None:
    projected = project_capability_http_request(
        CATALOG_ASSET_SEARCH,
        {"query": "重庆自然资源"},
    )
    assert json.loads(projected.model_dump_json())["query"] == {
        "q": "重庆自然资源"
    }
