"""REST, Capability, and MCP contracts for entity lineage."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import ENTITY_LINEAGE_RECORD
from data_agent.entity_lineage_authority import (
    EntityLineageConflictError,
    EntityLineageReceipt,
    EntityLineageRequest,
)
from data_agent.mcp_tool_registry import _mcp_record_entity_lineage_event
from data_agent.user_context import (
    current_tenant_id,
    current_user_id,
    current_user_role,
)

TENANT = "lineage-api"
NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


def _submission(*, tenant_id: str = TENANT, recorded_by: str = "human:operator-1"):
    source_a = f"gda://{tenant_id}/entity/parcel-a"
    source_b = f"gda://{tenant_id}/entity/parcel-b"
    target = f"gda://{tenant_id}/entity/parcel-merged"
    return EntityLineageRequest(
        tenant_id=tenant_id,
        event_ref=f"gda://{tenant_id}/entity_lineage/merge-001",
        lineage_kind="merge",
        effective_at=NOW,
        source_entity_refs=(source_a, source_b),
        target_entity_refs=(target,),
        source_version_refs=(
            f"gda://{tenant_id}/resource_version/chongqing-customer-v1",
        ),
        link_propagations=(),
        source_identity_redirects=(),
        idempotency_key="lineage.merge.001",
        owner_subject="team:natural-resource-governance",
        recorded_by=recorded_by,
        reason="Merge duplicate Chongqing parcel identities",
    )


def _receipt(submission: EntityLineageRequest) -> EntityLineageReceipt:
    return EntityLineageReceipt(
        tenant_id=submission.tenant_id,
        event_id=UUID("00000000-0000-4000-8000-000000000001"),
        event_ref=submission.event_ref,
        lineage_kind=submission.lineage_kind,
        effective_at=submission.effective_at,
        request_sha256=submission.request_sha256,
        event_sha256="a" * 64,
        recorded_at=NOW,
        source_count=2,
        target_count=1,
        retired_source_count=2,
        link_retraction_count=0,
        link_creation_count=0,
        link_deduplication_count=0,
        link_retract_only_count=0,
        source_identity_redirect_count=0,
    )


def _request(*, body: dict, headers: dict | None = None):
    request = MagicMock()

    async def read_json():
        return body

    request.json.side_effect = read_json
    request.headers = headers or {"x-request-id": "lineage-request-1"}
    request.path_params = {}
    request.query_params = {}
    return request


def _user(*, role: str = "platform_operator", tenant_id: str = TENANT):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": role, "tenant_id": tenant_id},
    )


def test_capability_declares_atomic_rest_sdk_and_mcp_surface() -> None:
    spec = ENTITY_LINEAGE_RECORD
    surfaces = {binding.surface.value: binding.status.value for binding in spec.surfaces}

    assert spec.version == "1.0.0"
    assert spec.policy.allowed_roles == ("admin", "platform_operator")
    assert spec.execution.idempotency.value == "required"
    assert surfaces["api"] == "implemented"
    assert surfaces["sdk"] == "implemented"
    assert surfaces["agent"] == "implemented"
    assert spec.mcp is not None
    assert spec.mcp.tool_name == "record_entity_lineage_event"
    assert spec.mcp_projection()["annotations"]["destructiveHint"] is True
    assert "/api/platform/v1/entity-authority/lineage-events" in (
        spec.openapi_projection()["paths"]
    )


@pytest.mark.parametrize(
    ("user", "status", "code"),
    (
        (None, 401, "unauthorized"),
        (_user(role="viewer"), 403, "platform_role_required"),
    ),
)
def test_route_requires_authentication_and_platform_role(user, status, code) -> None:
    request = _request(body=_submission().model_dump(mode="json"))
    with patch.object(routes, "_get_user_from_request", return_value=user):
        response = asyncio.run(routes.record_entity_lineage_event(request))
    assert response.status_code == status
    assert json.loads(response.body)["error"]["code"] == code


def test_route_enforces_contract_tenant_actor_idempotency_and_maps_conflict() -> None:
    submission = _submission()
    drift = _request(
        body=submission.model_dump(mode="json"),
        headers={"X-GDA-Capability-Fingerprint": "0" * 64},
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.record_entity_lineage_event(drift))
    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == (
        "capability_contract_mismatch"
    )

    other = _submission(tenant_id="lineage-other")
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(
            routes.record_entity_lineage_event(
                _request(body=other.model_dump(mode="json"))
            )
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "tenant_mismatch"

    spoofed = submission.model_copy(update={"recorded_by": "human:spoofed"})
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(
            routes.record_entity_lineage_event(
                _request(body=spoofed.model_dump(mode="json"))
            )
        )
    assert response.status_code == 403
    assert json.loads(response.body)["error"]["code"] == "actor_mismatch"

    mismatch = _request(
        body=submission.model_dump(mode="json"),
        headers={"idempotency-key": "different.key"},
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        response = asyncio.run(routes.record_entity_lineage_event(mismatch))
    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == (
        "idempotency_key_mismatch"
    )

    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch(
            "data_agent.entity_lineage_authority.EntityLineageAuthority.record",
            side_effect=EntityLineageConflictError("conflicting replay"),
        ),
    ):
        response = asyncio.run(
            routes.record_entity_lineage_event(
                _request(body=submission.model_dump(mode="json"))
            )
        )
    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == "entity_lineage_conflict"


def test_route_returns_standard_envelope_and_is_registered() -> None:
    submission = _submission()
    receipt = _receipt(submission)
    request = _request(
        body=submission.model_dump(mode="json"),
        headers={
            "x-request-id": "lineage-request-1",
            "X-GDA-Capability-Fingerprint": ENTITY_LINEAGE_RECORD.fingerprint,
            "idempotency-key": submission.idempotency_key,
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch(
            "data_agent.entity_lineage_authority.EntityLineageAuthority.record",
            return_value=receipt,
        ),
    ):
        response = asyncio.run(routes.record_entity_lineage_event(request))

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["request_id"] == "lineage-request-1"
    assert ENTITY_LINEAGE_RECORD.validate_output(payload["data"])[
        "event_sha256"
    ] == "a" * 64
    paths = {route.path for route in routes.get_platform_gateway_routes()}
    assert "/api/platform/v1/entity-authority/lineage-events" in paths


def test_mcp_enforces_context_actor_and_executes_canonical_contract() -> None:
    submission = _submission(recorded_by="agent:lineage-agent")
    receipt = _receipt(submission)
    arguments = {
        "tenant_id": submission.tenant_id,
        "event_ref": submission.event_ref,
        "lineage_kind": submission.lineage_kind.value,
        "effective_at": submission.effective_at.isoformat(),
        "source_entity_refs": list(submission.source_entity_refs),
        "target_entity_refs": list(submission.target_entity_refs),
        "source_version_refs": list(submission.source_version_refs),
        "link_propagations": [],
        "source_identity_redirects": [],
        "idempotency_key": submission.idempotency_key,
        "owner_subject": submission.owner_subject,
        "recorded_by": submission.recorded_by,
        "reason": submission.reason,
    }
    tenant_token = current_tenant_id.set(TENANT)
    user_token = current_user_id.set("lineage-agent")
    role_token = current_user_role.set("viewer")
    try:
        denied = json.loads(_mcp_record_entity_lineage_event(**arguments))
        assert denied["code"] == "platform_role_required"
        current_user_role.set("platform_operator")

        mismatch = json.loads(
            _mcp_record_entity_lineage_event(
                **{**arguments, "tenant_id": "lineage-other"}
            )
        )
        assert mismatch["code"] == "tenant_mismatch"
        spoofed = json.loads(
            _mcp_record_entity_lineage_event(
                **{**arguments, "recorded_by": "agent:spoofed"}
            )
        )
        assert spoofed["code"] == "actor_mismatch"

        with patch(
            "data_agent.entity_lineage_authority.EntityLineageAuthority.record",
            return_value=receipt,
        ) as record:
            payload = json.loads(_mcp_record_entity_lineage_event(**arguments))
        assert payload["event_sha256"] == "a" * 64
        assert payload["technical_baseline_status"] == (
            "technical_baseline_unreviewed"
        )
        assert record.call_args.args[0].recorded_by == "agent:lineage-agent"
    finally:
        current_user_role.reset(role_token)
        current_user_id.reset(user_token)
        current_tenant_id.reset(tenant_token)
