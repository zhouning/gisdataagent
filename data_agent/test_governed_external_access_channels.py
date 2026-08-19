from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, Mock

from starlette.requests import Request

from data_agent import governed_external_access as external_access_module
from data_agent.api import kb_routes
from data_agent.governed_external_access import GovernedExternalAccessService
from data_agent.governed_query_policy_authority import (
    InMemoryGovernedQueryPolicyAuthority,
)
from data_agent.mcp_hub import McpHubManager
from data_agent.mcp_tool_registry import _wrap_tool
from data_agent.user_context import (
    current_tenant_id,
    current_user_id,
    current_user_role,
)
from data_agent.uwm.abu_dhabi_flood import smartmakani_acquisition

TENANT = "tenant-a"
NOW = datetime(2026, 8, 19, 15, 0, tzinfo=UTC)
DOCUMENT_DIGEST = "a" * 64


class _User:
    identifier = "analyst-a"
    metadata = {"tenant_id": TENANT, "role": "analyst"}


def _deny_reader() -> InMemoryGovernedQueryPolicyAuthority:
    return InMemoryGovernedQueryPolicyAuthority(TENANT, clock=lambda: NOW)


def _request(path: str, body: dict) -> Request:
    delivered = False
    payload = json.dumps(body).encode()

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"content-type", b"application/json")],
            "query_string": b"",
            "path_params": {},
        },
        receive,
    )


def _governed_service(ledger: Mock) -> GovernedExternalAccessService:
    return GovernedExternalAccessService(ledger=ledger, now=lambda: NOW)


def test_rag_route_policy_deny_never_runs_embedding_or_database_search(
    monkeypatch,
) -> None:
    search = Mock()
    ledger = Mock()
    monkeypatch.setattr(kb_routes, "_get_user_from_request", lambda request: _User())
    monkeypatch.setattr(
        kb_routes, "_set_user_context", lambda user: ("analyst-a", "analyst")
    )
    monkeypatch.setattr(
        kb_routes,
        "resolve_governed_query_security_ports",
        lambda tenant_id: (_deny_reader(), Mock()),
    )
    monkeypatch.setattr(kb_routes, "_external_access", lambda: _governed_service(ledger))
    monkeypatch.setattr(
        "data_agent.governed_rag.search_governed_knowledge_base", search
    )
    tenant_token = current_tenant_id.set(TENANT)
    try:
        response = asyncio.run(
            kb_routes.kb_search(
                _request(
                    "/api/kb/search",
                    {
                        "query": "planning policy",
                        "kb_ids": [7],
                        "top_k": 3,
                        "document_pins": [
                            {
                                "resource_id": "kb:7/documents/11",
                                "version": f"sha256-{DOCUMENT_DIGEST}",
                                "content_sha256": DOCUMENT_DIGEST,
                            }
                        ],
                    },
                )
            )
        )
    finally:
        current_tenant_id.reset(tenant_token)

    assert response.status_code == 403
    search.assert_not_called()
    assert ledger.append.call_args.kwargs["phase"] == "denied"


def test_rag_route_requires_immutable_document_pins_before_resolving_security(
    monkeypatch,
) -> None:
    resolver = Mock()
    monkeypatch.setattr(kb_routes, "_get_user_from_request", lambda request: _User())
    monkeypatch.setattr(
        kb_routes, "_set_user_context", lambda user: ("analyst-a", "analyst")
    )
    monkeypatch.setattr(kb_routes, "resolve_governed_query_security_ports", resolver)
    tenant_token = current_tenant_id.set(TENANT)
    try:
        response = asyncio.run(
            kb_routes.kb_search(
                _request(
                    "/api/kb/search",
                    {"query": "planning policy", "kb_ids": [7]},
                )
            )
        )
    finally:
        current_tenant_id.reset(tenant_token)

    assert response.status_code == 400
    assert json.loads(response.body)["code"] == "immutable_document_pins_required"
    resolver.assert_not_called()


def test_legacy_graph_rag_route_is_explicitly_not_admitted(monkeypatch) -> None:
    legacy_search = Mock()
    monkeypatch.setattr(kb_routes, "_get_user_from_request", lambda request: _User())
    monkeypatch.setattr(kb_routes, "_set_user_context", lambda user: None)
    monkeypatch.setattr(
        "data_agent.knowledge_base.graph_rag_search", legacy_search
    )

    response = asyncio.run(
        kb_routes.kb_graph_search(
            _request("/api/kb/7/graph-search", {"query": "planning policy"})
        )
    )

    assert response.status_code == 409
    assert json.loads(response.body)["code"] == "legacy_graph_rag_not_admitted"
    legacy_search.assert_not_called()


def test_local_mcp_policy_deny_never_calls_tool(monkeypatch) -> None:
    tool = Mock(return_value={"status": "ok"})
    tool.__name__ = "buffer"
    ledger = Mock()
    monkeypatch.setattr(
        "data_agent.governed_query_security.resolve_governed_query_security_ports",
        lambda tenant_id: (_deny_reader(), Mock()),
    )
    monkeypatch.setattr(
        external_access_module,
        "GovernedExternalAccessService",
        lambda: _governed_service(ledger),
    )
    tenant_token = current_tenant_id.set(TENANT)
    user_token = current_user_id.set("gis-agent")
    role_token = current_user_role.set("analyst")
    try:
        result = json.loads(_wrap_tool(tool)(distance=100))
    finally:
        current_user_role.reset(role_token)
        current_user_id.reset(user_token)
        current_tenant_id.reset(tenant_token)

    assert result["status"] == "error"
    assert "denied" in result["message"]
    tool.assert_not_called()


def test_remote_mcp_policy_deny_precedes_tool_discovery(monkeypatch) -> None:
    ledger = Mock()
    hub = McpHubManager()
    discovery = MagicMock()
    monkeypatch.setattr(
        "data_agent.mcp_hub._get_toolset_tools",
        discovery,
    )
    monkeypatch.setattr(
        "data_agent.governed_query_security.resolve_governed_query_security_ports",
        lambda tenant_id: (_deny_reader(), Mock()),
    )
    monkeypatch.setattr(
        external_access_module,
        "GovernedExternalAccessService",
        lambda: _governed_service(ledger),
    )
    tenant_token = current_tenant_id.set(TENANT)
    user_token = current_user_id.set("gis-agent")
    role_token = current_user_role.set("analyst")
    try:
        try:
            asyncio.run(hub.call_tool("arcpy", "buffer", {"distance": 100}))
        except Exception as exc:
            error = exc
        else:
            raise AssertionError("denied MCP invocation unexpectedly succeeded")
    finally:
        current_user_role.reset(role_token)
        current_user_id.reset(user_token)
        current_tenant_id.reset(tenant_token)

    assert "denied" in str(error)
    discovery.assert_not_called()


def test_observation_policy_deny_precedes_connector_and_filesystem(
    monkeypatch, tmp_path
) -> None:
    ledger = Mock()
    connector = MagicMock()
    spec = smartmakani_acquisition.SmartMakaniLayerSpec(
        layer_id=37,
        role="stormwater_pipelines",
        out_fields=("OBJECTID",),
        bbox_wgs84=None,
        dataset_key="pipelines",
    )
    monkeypatch.setattr(
        smartmakani_acquisition,
        "resolve_governed_query_security_ports",
        lambda tenant_id: (_deny_reader(), Mock()),
    )
    monkeypatch.setattr(
        smartmakani_acquisition,
        "GovernedExternalAccessService",
        lambda: _governed_service(ledger),
    )
    tenant_token = current_tenant_id.set(TENANT)
    role_token = current_user_role.set("analyst")
    try:
        try:
            asyncio.run(
                smartmakani_acquisition.download_layer(
                    tmp_path,
                    spec,
                    connector=connector,
                    page_size=100,
                )
            )
        except Exception as exc:
            error = exc
        else:
            raise AssertionError("denied observation acquisition unexpectedly succeeded")
    finally:
        current_user_role.reset(role_token)
        current_tenant_id.reset(tenant_token)

    assert "denied" in str(error)
    connector.create_query_snapshot.assert_not_called()
    assert list(tmp_path.iterdir()) == []
