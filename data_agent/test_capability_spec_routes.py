from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from data_agent.api import capability_spec_routes as routes
from data_agent.capability_registry import get_capability_registry


def _request(path: str, query_string: bytes = b"") -> Request:
    return Request({
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "query_string": query_string,
    })


def _authenticate(monkeypatch) -> None:
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: {"id": "analyst"})
    monkeypatch.setattr(routes, "_set_user_context", lambda user: ("analyst", "analyst"))


@pytest.mark.asyncio
async def test_capability_registry_requires_authentication(monkeypatch) -> None:
    monkeypatch.setattr(routes, "_get_user_from_request", lambda request: None)
    response = await routes.capability_specs_list(_request("/api/capability-specs"))
    assert response.status_code == 401
    assert json.loads(response.body) == {"error": "Unauthorized"}


@pytest.mark.asyncio
async def test_llm_disabled_manifest_preserves_deterministic_surfaces(monkeypatch) -> None:
    _authenticate(monkeypatch)
    response = await routes.capability_specs_list(
        _request("/api/capability-specs", b"llm_mode=disabled")
    )
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["schema"] == "gda.capability-registry.v1"
    assert payload["count"] == len(get_capability_registry().list_specs())
    capability = next(
        item
        for item in payload["capabilities"]
        if item["capability_id"] == "catalog.asset.search"
    )
    assert capability["capability_id"] == "catalog.asset.search"
    assert "api" in capability["available_surfaces"]
    assert "cli" in capability["available_surfaces"]
    assert "agent" not in capability["available_surfaces"]
    manual_run = next(
        item
        for item in payload["capabilities"]
        if item["capability_id"] == "dataops.run.submit-manual"
    )
    assert manual_run["operation"] == "long_running"
    assert manual_run["available_surfaces"] == [
        "web",
        "api",
        "sdk",
        "cli",
        "tui",
        "notebook",
    ]
    cancel = next(
        item
        for item in payload["capabilities"]
        if item["capability_id"] == "dataops.run.cancel"
    )
    assert cancel["operation"] == "command"
    assert cancel["available_surfaces"] == [
        "web",
        "api",
        "sdk",
        "cli",
        "tui",
        "notebook",
    ]
    governed_query = next(
        item
        for item in payload["capabilities"]
        if item["capability_id"] == "semantic.query.execute"
    )
    assert governed_query["operation"] == "command"
    assert governed_query["available_surfaces"] == ["api", "agent"]
    entity_batch = next(
        item
        for item in payload["capabilities"]
        if item["capability_id"] == "entity.authority.batch.ingest"
    )
    assert entity_batch["operation"] == "command"
    assert "api" in entity_batch["available_surfaces"]
    assert "agent" in entity_batch["available_surfaces"]
    entity_lineage = next(
        item
        for item in payload["capabilities"]
        if item["capability_id"] == "entity.lineage.record"
    )
    assert entity_lineage["operation"] == "command"
    assert "api" in entity_lineage["available_surfaces"]
    assert "agent" in entity_lineage["available_surfaces"]


@pytest.mark.asyncio
async def test_capability_detail_returns_bound_projections(monkeypatch) -> None:
    _authenticate(monkeypatch)
    request = _request("/api/capability-specs/catalog.asset.search")
    request.scope["path_params"] = {"capability_id": "catalog.asset.search"}
    response = await routes.capability_spec_detail(request)
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["spec"]["capability_id"] == "catalog.asset.search"
    assert payload["projections"]["mcp"]["name"] == "search_catalog"
    assert "/api/catalog/search" in payload["projections"]["openapi"]["paths"]
    assert payload["fingerprint"] == payload["projections"]["mcp"]["_meta"]["gda/fingerprint"]


@pytest.mark.asyncio
async def test_long_running_detail_returns_openapi_and_asyncapi(monkeypatch) -> None:
    _authenticate(monkeypatch)
    request = _request("/api/capability-specs/dataops.run.submit-manual")
    request.scope["path_params"] = {
        "capability_id": "dataops.run.submit-manual"
    }
    response = await routes.capability_spec_detail(request)
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["spec"]["operation"] == "long_running"
    assert set(payload["projections"]) == {"openapi", "asyncapi"}
    assert payload["projections"]["asyncapi"]["asyncapi"] == "3.0.0"
    message = payload["projections"]["asyncapi"]["components"]["messages"][
        "capabilityEvent"
    ]
    responses = payload["projections"]["openapi"]["paths"][
        "/api/platform/v1/dataops/manual-runs"
    ]["post"]["responses"]
    assert set(responses) == {"200", "202", "401", "403"}
    assert message["x-gda-capability-fingerprint"] == payload["fingerprint"]


@pytest.mark.asyncio
async def test_command_detail_returns_path_aware_openapi_and_asyncapi(monkeypatch) -> None:
    _authenticate(monkeypatch)
    request = _request("/api/capability-specs/dataops.run.cancel")
    request.scope["path_params"] = {"capability_id": "dataops.run.cancel"}
    response = await routes.capability_spec_detail(request)
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["spec"]["operation"] == "command"
    assert set(payload["projections"]) == {"openapi", "asyncapi"}
    operation = payload["projections"]["openapi"]["paths"][
        "/api/platform/v1/runs/{run_id}/cancel"
    ]["post"]
    assert set(operation["responses"]) == {"200", "202", "401", "403"}
    assert operation["parameters"][0]["in"] == "path"
    assert operation["parameters"][0]["name"] == "run_id"
    assert operation["parameters"][1]["in"] == "header"
    assert operation["parameters"][1]["name"] == (
        "X-GDA-Capability-Fingerprint"
    )
    assert payload["projections"]["asyncapi"]["asyncapi"] == "3.0.0"


@pytest.mark.asyncio
async def test_governed_query_detail_returns_openapi_and_mcp(monkeypatch) -> None:
    _authenticate(monkeypatch)
    request = _request("/api/capability-specs/semantic.query.execute")
    request.scope["path_params"] = {"capability_id": "semantic.query.execute"}
    response = await routes.capability_spec_detail(request)
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["spec"]["capability_id"] == "semantic.query.execute"
    assert set(payload["projections"]) == {"openapi", "mcp"}
    assert "/api/governed-query" in payload["projections"]["openapi"]["paths"]
    assert payload["projections"]["mcp"]["name"] == "execute_governed_query"


@pytest.mark.asyncio
async def test_gis_analysis_detail_returns_run_openapi_and_asyncapi(monkeypatch) -> None:
    _authenticate(monkeypatch)
    request = _request("/api/capability-specs/gis.analysis.execute")
    request.scope["path_params"] = {"capability_id": "gis.analysis.execute"}
    response = await routes.capability_spec_detail(request)
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["spec"]["operation"] == "long_running"
    assert set(payload["projections"]) == {"openapi", "asyncapi"}
    operation = payload["projections"]["openapi"]["paths"][
        "/api/platform/v1/gis-analysis-runs"
    ]["post"]
    assert set(operation["responses"]) == {"200", "202", "401", "403"}
    assert payload["spec"]["execution"]["cancellable"] is True
    assert payload["projections"]["asyncapi"]["asyncapi"] == "3.0.0"


@pytest.mark.asyncio
async def test_entity_authority_detail_returns_openapi_and_mcp(monkeypatch) -> None:
    _authenticate(monkeypatch)
    request = _request(
        "/api/capability-specs/entity.authority.batch.ingest"
    )
    request.scope["path_params"] = {
        "capability_id": "entity.authority.batch.ingest"
    }
    response = await routes.capability_spec_detail(request)
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert set(payload["projections"]) == {"openapi", "mcp"}
    assert payload["projections"]["mcp"]["name"] == (
        "ingest_entity_authority_batch"
    )
    assert payload["projections"]["mcp"]["annotations"]["destructiveHint"] is True


def test_capability_routes_are_mounted() -> None:
    from data_agent.frontend_api import get_frontend_api_routes

    mounted = {route.path for route in get_frontend_api_routes()}
    assert "/api/capability-specs" in mounted
    assert "/api/capability-specs/{capability_id:str}" in mounted
