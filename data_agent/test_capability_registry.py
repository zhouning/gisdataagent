from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from data_agent.capability_registry import (
    CAPABILITY_FINGERPRINT_HEADER,
    CATALOG_ASSET_SEARCH,
    DATAOPS_MANUAL_RUN_SUBMIT,
    DATAOPS_RUN_CANCEL,
    GIS_ANALYSIS_EXECUTE,
    GOVERNED_SEMANTIC_QUERY,
    CapabilityContractError,
    CapabilityFingerprintMismatchError,
    CapabilityInputError,
    CapabilityRegistry,
    CapabilitySpec,
    IdempotencyMode,
    LlmMode,
    OperationKind,
    PreviewMode,
    ResultMode,
    SideEffect,
    Surface,
    build_capability_json_schema,
    get_capability_registry,
)
from data_agent.dataops_cancel import DataOpsCancelRequest, DataOpsCancelResponse
from data_agent.dataops_manual import ManualDataOpsRunRequest, ManualDataOpsRunResponse
from data_agent.governed_query import GovernedQueryRequest, GovernedQueryResponse


def test_catalog_search_is_a_complete_p0_parity_contract() -> None:
    spec = get_capability_registry().get("catalog.asset.search")

    assert spec is CATALOG_ASSET_SEARCH
    assert {binding.surface for binding in spec.surfaces} == set(Surface)
    assert set(spec.available_surfaces(LlmMode.OPTIONAL)) == set(Surface)
    assert set(spec.available_surfaces(LlmMode.DISABLED)) == set(Surface) - {
        Surface.AGENT
    }
    assert len(spec.fingerprint) == 64


def test_catalog_search_uses_one_schema_for_openapi_and_mcp() -> None:
    spec = CATALOG_ASSET_SEARCH
    openapi = spec.openapi_projection()
    operation = openapi["paths"]["/api/catalog/search"]["get"]
    mcp = spec.mcp_projection()

    assert operation["parameters"][:-1] == [
        {
            "name": "q",
            "in": "query",
            "required": True,
            "schema": spec.input.json_schema["properties"]["query"],
            "x-gda-canonical-name": "query",
        }
    ]
    assert operation["parameters"][-1] == {
        "name": CAPABILITY_FINGERPRINT_HEADER,
        "in": "header",
        "required": False,
        "description": (
            "Installed client CapabilitySpec fingerprint. When supplied, "
            "the server rejects contract drift before execution."
        ),
        "schema": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
    }
    response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response_schema == spec.output.json_schema
    assert mcp["inputSchema"] == spec.input.json_schema
    assert mcp["outputSchema"] == spec.output.json_schema
    assert mcp["annotations"] == {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
    }
    assert operation["x-gda-capability-fingerprint"] == mcp["_meta"]["gda/fingerprint"]


def test_catalog_search_validates_boundary_payloads() -> None:
    spec = CATALOG_ASSET_SEARCH
    assert spec.validate_input({"query": "重庆地类图斑"}) == {
        "query": "重庆地类图斑"
    }
    with pytest.raises(CapabilityInputError, match="non-empty"):
        spec.validate_input({"query": ""})
    with pytest.raises(CapabilityInputError, match="does not match"):
        spec.validate_input({"query": "   "})
    with pytest.raises(CapabilityInputError, match="Additional properties"):
        spec.validate_input({"query": "roads", "tenant_id": "spoofed"})

    assert spec.validate_output({
        "status": "success",
        "count": 0,
        "assets": [],
        "message": "Found 0 assets",
    })["status"] == "success"
    assert spec.validate_output({
        "status": "error",
        "message": "Database not configured",
    })["status"] == "error"


def test_manual_dataops_run_is_a_truthful_long_running_contract() -> None:
    spec = get_capability_registry().get("dataops.run.submit-manual")

    assert spec is DATAOPS_MANUAL_RUN_SUBMIT
    assert spec.operation is OperationKind.LONG_RUNNING
    assert spec.side_effect is SideEffect.EXTERNAL_WRITE
    assert spec.execution.idempotency is IdempotencyMode.REQUIRED
    assert spec.execution.preview is PreviewMode.REQUIRED
    assert spec.execution.result is ResultMode.RUN_REF
    assert spec.execution.cancellable is True
    assert spec.execution.reconcilable is True
    assert spec.input.json_schema == build_capability_json_schema(
        ManualDataOpsRunRequest,
        "gda.dataops.manual-run-request.v1",
    )
    assert spec.output.json_schema == build_capability_json_schema(
        ManualDataOpsRunResponse,
        "gda.dataops.manual-run-admission.v1",
    )
    deterministic_clients = {
        Surface.WEB,
        Surface.API,
        Surface.SDK,
        Surface.CLI,
        Surface.TUI,
        Surface.NOTEBOOK,
    }
    assert set(spec.available_surfaces(LlmMode.DISABLED)) == deterministic_clients
    assert set(spec.available_surfaces(LlmMode.OPTIONAL)) == deterministic_clients


def test_manual_dataops_run_validates_canonical_client_owned_input() -> None:
    spec = DATAOPS_MANUAL_RUN_SUBMIT
    payload = {
        "client_request_id": "operator-console-20260804-001",
        "definition_version_id": str(UUID("30000000-0000-4000-8000-000000000010")),
        "logical_start": datetime(2026, 8, 1, tzinfo=UTC).isoformat(),
        "logical_end": datetime(2026, 8, 2, tzinfo=UTC).isoformat(),
        "input_bindings": [
            {
                "binding_name": "source",
                "resource_version_id": "30000000-0000-4000-8000-000000000020",
                "semantic_type": "gis.land_use.parcels",
            }
        ],
        "execution_plan_artifact_id": "30000000-0000-4000-8000-000000000030",
        "purpose": "run a governed parcel audit",
        "config_fingerprint": "a" * 64,
    }

    assert spec.validate_input(payload) == payload
    with pytest.raises(CapabilityInputError, match="Additional properties"):
        spec.validate_input({**payload, "tenant_id": "spoofed"})
    with pytest.raises(CapabilityInputError, match="execution_plan_artifact_id"):
        spec.validate_input({
            key: value
            for key, value in payload.items()
            if key != "execution_plan_artifact_id"
        })


def test_manual_dataops_protocol_projections_share_one_contract() -> None:
    spec = DATAOPS_MANUAL_RUN_SUBMIT
    openapi = spec.openapi_projection()
    operation = openapi["paths"]["/api/platform/v1/dataops/manual-runs"]["post"]
    response_schema = operation["responses"]["202"]["content"]["application/json"]["schema"]
    asyncapi = spec.asyncapi_projection()
    message = asyncapi["components"]["messages"]["capabilityEvent"]

    assert operation["requestBody"]["content"]["application/json"]["schema"] == (
        spec.input.json_schema
    )
    assert operation["parameters"][0]["name"] == CAPABILITY_FINGERPRINT_HEADER
    assert operation["parameters"][0]["in"] == "header"
    assert operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == response_schema
    assert response_schema["properties"]["data"] == spec.output.json_schema
    assert set(response_schema["required"]) == {
        "data", "error", "request_id", "created",
    }
    Draft202012Validator.check_schema(response_schema)
    assert asyncapi["asyncapi"] == "3.0.0"
    assert asyncapi["defaultContentType"] == "application/cloudevents+json"
    assert message["name"] == "gda.platform-run.status-changed.v1"
    assert message["payload"]["properties"]["type"]["const"] == message["name"]
    assert message["x-gda-capability-fingerprint"] == spec.fingerprint


def test_dataops_cancel_is_a_truthful_p0_command_contract() -> None:
    spec = get_capability_registry().get("dataops.run.cancel")

    assert spec is DATAOPS_RUN_CANCEL
    assert spec.operation is OperationKind.COMMAND
    assert spec.side_effect is SideEffect.EXTERNAL_WRITE
    assert spec.execution.idempotency is IdempotencyMode.REQUIRED
    assert spec.execution.preview is PreviewMode.UNSUPPORTED
    assert spec.execution.result is ResultMode.SYNCHRONOUS
    assert spec.execution.cancellable is False
    assert spec.execution.reconcilable is True
    assert spec.policy.action == "dolphinscheduler.cancel"
    assert spec.input.json_schema == build_capability_json_schema(
        DataOpsCancelRequest,
        "gda.dataops.cancel-request.v1",
    )
    assert spec.output.json_schema == build_capability_json_schema(
        DataOpsCancelResponse,
        "gda.dataops.cancel-admission.v1",
    )
    assert set(spec.available_surfaces(LlmMode.DISABLED)) == {
        Surface.WEB,
        Surface.API,
        Surface.SDK,
        Surface.CLI,
        Surface.TUI,
        Surface.NOTEBOOK,
    }


def test_dataops_cancel_validates_canonical_path_and_body_input() -> None:
    spec = DATAOPS_RUN_CANCEL
    payload = {
        "run_id": "30000000-0000-4000-8000-000000000040",
        "client_request_id": "cancel-console-20260804-001",
        "expected_state_version": 2,
        "reason": "operator cancelled an obsolete source refresh",
    }

    assert spec.validate_input(payload) == payload
    with pytest.raises(CapabilityInputError, match="run_id"):
        spec.validate_input({key: value for key, value in payload.items() if key != "run_id"})
    with pytest.raises(CapabilityInputError, match="Additional properties"):
        spec.validate_input({**payload, "tenant_id": "spoofed"})


def test_dataops_cancel_openapi_splits_path_from_canonical_body() -> None:
    spec = DATAOPS_RUN_CANCEL
    openapi = spec.openapi_projection()
    operation = openapi["paths"]["/api/platform/v1/runs/{run_id}/cancel"]["post"]
    body_schema = operation["requestBody"]["content"]["application/json"]["schema"]
    response_schema = operation["responses"]["202"]["content"]["application/json"][
        "schema"
    ]

    assert operation["parameters"][:-1] == [
        {
            "name": "run_id",
            "in": "path",
            "required": True,
            "schema": spec.input.json_schema["properties"]["run_id"],
            "x-gda-canonical-name": "run_id",
        }
    ]
    assert operation["parameters"][-1]["name"] == CAPABILITY_FINGERPRINT_HEADER
    assert operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == response_schema
    assert operation["parameters"][-1]["in"] == "header"
    assert "run_id" not in body_schema["properties"]
    assert set(body_schema["required"]) == {
        "client_request_id",
        "expected_state_version",
        "reason",
    }
    assert body_schema["$id"].endswith(".http-body.json")
    assert response_schema["properties"]["data"] == spec.output.json_schema
    assert set(response_schema["required"]) == {
        "data",
        "error",
        "request_id",
        "created",
    }
    Draft202012Validator.check_schema(body_schema)
    Draft202012Validator.check_schema(response_schema)

    asyncapi = spec.asyncapi_projection()
    message = asyncapi["components"]["messages"]["capabilityEvent"]
    assert message["name"] == "gda.platform-run.status-changed.v1"
    assert message["x-gda-capability-fingerprint"] == spec.fingerprint


def test_governed_query_uses_one_strict_contract_for_openapi_and_mcp() -> None:
    spec = get_capability_registry().get("semantic.query.execute")

    assert spec is GOVERNED_SEMANTIC_QUERY
    assert spec.operation is OperationKind.COMMAND
    assert spec.side_effect is SideEffect.CONTROL_WRITE
    assert spec.execution.idempotency is IdempotencyMode.REQUIRED
    assert spec.tier == "P1"
    assert spec.version == "4.1.0"
    assert spec.input.json_schema == build_capability_json_schema(
        GovernedQueryRequest,
        "gda.governed-query-request.v4",
    )
    assert spec.output.json_schema == build_capability_json_schema(
        GovernedQueryResponse,
        "gda.governed-query-result.v4",
    )
    assert set(spec.available_surfaces(LlmMode.DISABLED)) == {
        Surface.API,
        Surface.AGENT,
    }
    openapi = spec.openapi_projection()
    operation = openapi["paths"]["/api/governed-query"]["post"]
    mcp = spec.mcp_projection()
    assert operation["requestBody"]["content"]["application/json"]["schema"] == (
        mcp["inputSchema"]
    )
    assert "rag_request" in spec.input.json_schema["properties"]
    assert operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == mcp["outputSchema"]
    assert mcp["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
    }


def test_gis_analysis_is_a_truthful_long_running_capability() -> None:
    spec = get_capability_registry().get("gis.analysis.execute")

    assert spec is GIS_ANALYSIS_EXECUTE
    assert spec.operation is OperationKind.LONG_RUNNING
    assert spec.side_effect is SideEffect.DATA_WRITE
    assert spec.execution.idempotency is IdempotencyMode.REQUIRED
    assert spec.execution.result is ResultMode.RUN_REF
    assert spec.execution.cancellable is True
    assert spec.execution.reconcilable is False
    assert set(spec.available_surfaces(LlmMode.DISABLED)) == {Surface.API}
    assert spec.openapi_projection()["paths"][
        "/api/platform/v1/gis-analysis-runs"
    ]["post"]["responses"]["202"]
    message = spec.asyncapi_projection()["components"]["messages"][
        "capabilityEvent"
    ]
    assert message["name"] == "gda.platform-run.status-changed.v1"
    assert message["x-gda-capability-fingerprint"] == spec.fingerprint


def test_governed_query_capability_rejects_client_identity_fields() -> None:
    payload = {
        "request_id": "query-001",
        "question": "土地是什么？",
        "purpose": "ontology query",
        "channel": "ontology",
        "ontology_plan": {
            "query_type": "concept_explanation",
            "subject": "土地",
        },
    }
    assert GOVERNED_SEMANTIC_QUERY.validate_input(payload) == payload
    with pytest.raises(CapabilityInputError, match="Additional properties"):
        GOVERNED_SEMANTIC_QUERY.validate_input({**payload, "tenant_id": "spoofed"})


def test_long_running_contract_rejects_missing_side_effect() -> None:
    payload = DATAOPS_MANUAL_RUN_SUBMIT.model_dump(mode="python")
    payload["side_effect"] = SideEffect.NONE
    with pytest.raises(
        ValidationError,
        match="long-running capability must declare its side effect",
    ):
        CapabilitySpec.model_validate(payload)


def test_query_contract_rejects_write_side_effects() -> None:
    payload = CATALOG_ASSET_SEARCH.model_dump(mode="python")
    payload["side_effect"] = SideEffect.DATA_WRITE
    with pytest.raises(ValidationError, match="query capability cannot declare side effects"):
        CapabilitySpec.model_validate(payload)


def test_high_risk_command_contract_requires_idempotent_synchronous_admission() -> None:
    non_idempotent = DATAOPS_RUN_CANCEL.model_dump(mode="python")
    non_idempotent["execution"]["idempotency"] = IdempotencyMode.OPTIONAL
    with pytest.raises(ValidationError, match="high-risk command.*idempotency"):
        CapabilitySpec.model_validate(non_idempotent)

    asynchronous = DATAOPS_RUN_CANCEL.model_dump(mode="python")
    asynchronous["execution"]["result"] = ResultMode.RUN_REF
    with pytest.raises(ValidationError, match="command capability must return synchronously"):
        CapabilitySpec.model_validate(asynchronous)


def test_explicit_invocation_fingerprint_fails_closed_on_contract_drift() -> None:
    spec = DATAOPS_RUN_CANCEL
    spec.assert_invocation_fingerprint(None)
    spec.assert_invocation_fingerprint(spec.fingerprint)

    with pytest.raises(
        CapabilityFingerprintMismatchError,
        match="capability contract mismatch",
    ):
        spec.assert_invocation_fingerprint("f" * 64)


def test_registry_rejects_duplicate_version_and_resolves_latest() -> None:
    registry = CapabilityRegistry((CATALOG_ASSET_SEARCH,))
    with pytest.raises(CapabilityContractError, match="duplicate capability version"):
        registry.register(CATALOG_ASSET_SEARCH)

    payload = deepcopy(CATALOG_ASSET_SEARCH.model_dump(mode="python"))
    payload["version"] = "1.1.0"
    newer = CapabilitySpec.model_validate(payload)
    registry.register(newer)
    assert registry.get("catalog.asset.search") is newer
    assert registry.get("catalog.asset.search", "1.0.0") is CATALOG_ASSET_SEARCH


def test_public_catalog_search_enforces_the_capability_input(monkeypatch) -> None:
    from data_agent import data_catalog

    monkeypatch.setattr(data_catalog, "get_engine", lambda: None)
    with pytest.raises(CapabilityInputError):
        data_catalog.search_data_assets("")
    assert data_catalog.search_data_assets("roads") == {
        "status": "error",
        "message": "Database not configured",
    }


def test_declared_catalog_surface_entrypoints_exist() -> None:
    from data_agent.cli import catalog_search
    from data_agent.data_catalog import search_data_assets
    from data_agent.mcp_tool_registry import TOOL_DEFINITIONS

    assert callable(catalog_search)
    assert callable(search_data_assets)
    mcp_definition = next(
        item for item in TOOL_DEFINITIONS if item["name"] == "search_catalog"
    )
    assert mcp_definition["annotations"].readOnlyHint is True

    repo_root = Path(__file__).resolve().parents[1]
    web_source = (
        repo_root / "frontend/src/components/datapanel/CatalogTab.tsx"
    ).read_text(encoding="utf-8")
    tui_source = (repo_root / "data_agent/tui.py").read_text(encoding="utf-8")
    api_source = (repo_root / "data_agent/frontend_api.py").read_text(
        encoding="utf-8"
    )
    assert "/api/catalog/search" in web_source
    assert 'cmd == "/catalog"' in tui_source
    assert 'Route("/api/catalog/search"' in api_source


def test_declared_governed_query_mcp_entrypoint_exists() -> None:
    from data_agent.mcp_tool_registry import TOOL_DEFINITIONS, _get_tool_functions

    definition = next(
        item for item in TOOL_DEFINITIONS if item["name"] == "execute_governed_query"
    )
    assert definition["annotations"].readOnlyHint is False
    assert definition["annotations"].destructiveHint is False
    entrypoint = _get_tool_functions()["execute_governed_query"]
    assert callable(entrypoint)
    assert "rag_request" in entrypoint.__annotations__


def test_declared_entity_authority_mcp_entrypoint_exists() -> None:
    from data_agent.mcp_tool_registry import TOOL_DEFINITIONS, _get_tool_functions

    definition = next(
        item
        for item in TOOL_DEFINITIONS
        if item["name"] == "ingest_entity_authority_batch"
    )
    assert definition["annotations"].readOnlyHint is False
    assert definition["annotations"].destructiveHint is True
    entrypoint = _get_tool_functions()["ingest_entity_authority_batch"]
    assert callable(entrypoint)
    assert "items" in entrypoint.__annotations__


def test_declared_entity_lineage_mcp_entrypoint_exists() -> None:
    from data_agent.mcp_tool_registry import TOOL_DEFINITIONS, _get_tool_functions

    definition = next(
        item
        for item in TOOL_DEFINITIONS
        if item["name"] == "record_entity_lineage_event"
    )
    assert definition["annotations"].readOnlyHint is False
    assert definition["annotations"].destructiveHint is True
    entrypoint = _get_tool_functions()["record_entity_lineage_event"]
    assert callable(entrypoint)
    assert "link_propagations" in entrypoint.__annotations__


def test_declared_dataops_client_surface_entrypoints_exist() -> None:
    from data_agent.capability_client import CapabilityClient
    from data_agent.cli import capability_invoke

    assert callable(CapabilityClient.invoke)
    assert callable(capability_invoke)
    for spec in (DATAOPS_MANUAL_RUN_SUBMIT, DATAOPS_RUN_CANCEL):
        bindings = {binding.surface: binding for binding in spec.surfaces}
        assert bindings[Surface.SDK].entrypoint == (
            "python:data_agent.capability_client:CapabilityClient.invoke"
        )
        assert bindings[Surface.CLI].entrypoint.endswith(spec.capability_id)
        assert bindings[Surface.TUI].entrypoint.startswith(
            f"tui:/capability invoke {spec.capability_id}"
        )
        assert bindings[Surface.NOTEBOOK].entrypoint == (
            "python:data_agent.capability_client:CapabilityClient.invoke"
        )
        assert bindings[Surface.WEB].entrypoint == (
            "frontend:PlatformCapabilitiesPanel"
        )
        assert bindings[Surface.WEB].status.value == "implemented"
        assert bindings[Surface.AGENT].status.value == "planned"
