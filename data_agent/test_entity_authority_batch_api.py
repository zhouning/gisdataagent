from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from data_agent.api import platform_gateway_routes as routes
from data_agent.capability_registry import ENTITY_AUTHORITY_BATCH_INGEST
from data_agent.chongqing_entity_link_baseline import (
    build_chongqing_entity_link_baseline,
)
from data_agent.entity_authority_batch import (
    EntityAuthorityBatchRequest,
    EntityAuthorityBatchResponse,
    execute_entity_authority_batch,
)
from data_agent.mcp_tool_registry import _mcp_ingest_entity_authority_batch
from data_agent.platform_contracts import build_resource_urn
from data_agent.temporal_entity_authority import (
    TemporalEntityAssertionDraft,
    TemporalEntityConflictError,
)
from data_agent.user_context import (
    current_tenant_id,
    current_user_id,
    current_user_role,
)

TENANT = "tenant-a"
ACTOR = "human:operator-1"
NOW = datetime(2026, 8, 14, 12, tzinfo=UTC)


def _temporal_item(
    index: int = 1,
    *,
    tenant_id: str = TENANT,
    recorded_by: str = ACTOR,
) -> TemporalEntityAssertionDraft:
    return TemporalEntityAssertionDraft(
        tenant_id=tenant_id,
        entity_ref=build_resource_urn(tenant_id, "entity", f"parcel-{index}"),
        object_type="natural_resource.parcel",
        lifecycle_state="active",
        attributes={"parcel_id": index},
        valid_from=NOW,
        source_version_refs=(
            build_resource_urn(
                tenant_id,
                "resource_version",
                "chongqing-customer-v1",
            ),
        ),
        mutation_kind="initial",
        idempotency_key=f"cq.entity.{index}",
        owner_subject="team:data-platform",
        recorded_by=recorded_by,
        reason="Load the Chongqing customer technical baseline",
    )


def _batch(
    *items: TemporalEntityAssertionDraft,
    tenant_id: str = TENANT,
    batch_size: int = 250,
) -> EntityAuthorityBatchRequest:
    return EntityAuthorityBatchRequest(
        batch_type="temporal_entity_assertions",
        tenant_id=tenant_id,
        idempotency_key="cq.entity-authority.batch.1",
        batch_size=batch_size,
        items=items or (_temporal_item(),),
    )


def _request(*, body=None, headers=None):
    request = MagicMock()

    async def read_json():
        return body or {}

    request.json.side_effect = read_json
    request.headers = headers or {"x-request-id": "request-1"}
    request.path_params = {}
    request.query_params = {}
    return request


def _user(*, role: str = "platform_operator", tenant_id: str = TENANT):
    return SimpleNamespace(
        identifier="operator-1",
        metadata={"role": role, "tenant_id": tenant_id},
    )


class _FakeTemporalAuthority:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def record_batch(self, drafts):
        batch = tuple(drafts)
        self.batch_sizes.append(len(batch))
        return batch


class _FakeLinkAuthority:
    def __init__(self) -> None:
        self.operations: list[str] = []

    def bind_sources_batch(self, drafts):
        self.operations.append("source_identity_bindings")
        return tuple(drafts)

    def register_link_types_batch(self, drafts):
        self.operations.append("link_types")
        return tuple(drafts)

    def record_links_batch(self, drafts):
        self.operations.append("link_assertions")
        return tuple(drafts)


def test_batch_contract_rejects_mixed_type_and_tenant_items() -> None:
    item = _temporal_item()
    payload = _batch(item).model_dump(mode="json")
    payload["batch_type"] = "link_assertions"
    with pytest.raises(ValidationError, match="items must match batch_type"):
        EntityAuthorityBatchRequest.model_validate(payload)

    other_tenant = _temporal_item(tenant_id="tenant-b")
    with pytest.raises(ValidationError, match="must match every item"):
        _batch(item, other_tenant)

    payload = _batch(item).model_dump(mode="json")
    payload["items"] = []
    with pytest.raises(ValidationError, match="at least 1 item"):
        EntityAuthorityBatchRequest.model_validate(payload)

    payload = _batch(item).model_dump(mode="json")
    payload["batch_size"] = 501
    with pytest.raises(ValidationError, match="less than or equal to 500"):
        EntityAuthorityBatchRequest.model_validate(payload)


def test_executor_chunks_and_replay_preserves_state_fingerprint() -> None:
    authority = _FakeTemporalAuthority()
    request = _batch(
        _temporal_item(1),
        _temporal_item(2),
        _temporal_item(3),
        batch_size=2,
    )

    first = execute_entity_authority_batch(
        request,
        temporal_authority=authority,  # type: ignore[arg-type]
    )
    second = execute_entity_authority_batch(
        request,
        temporal_authority=authority,  # type: ignore[arg-type]
    )

    assert authority.batch_sizes == [2, 1, 2, 1]
    assert first.logical_operation_count == 3
    assert first.batch_count == 2
    assert first.entity_count == 3
    assert first.state_fingerprint == second.state_fingerprint
    assert first.request_sha256 == second.request_sha256
    assert first.technical_baseline_status == "technical_baseline_unreviewed"
    assert first.decision_status == "assisted_precheck_not_for_production_decision"


def test_executor_dispatches_all_link_batch_types() -> None:
    baseline = build_chongqing_entity_link_baseline()
    link_authority = _FakeLinkAuthority()
    cases = (
        (
            "source_identity_bindings",
            (baseline.source_binding_drafts[0],),
            "binding_count",
        ),
        ("link_types", (baseline.link_type_draft,), "link_type_count"),
        (
            "link_assertions",
            (baseline.link_assertion_drafts[0],),
            "link_assertion_count",
        ),
    )

    for batch_type, items, count_field in cases:
        request = EntityAuthorityBatchRequest(
            batch_type=batch_type,
            tenant_id=baseline.tenant_id,
            idempotency_key=f"cq.{batch_type}.batch.1",
            items=items,
        )
        result = execute_entity_authority_batch(
            request,
            temporal_authority=_FakeTemporalAuthority(),  # type: ignore[arg-type]
            link_authority=link_authority,  # type: ignore[arg-type]
        )
        assert getattr(result, count_field) == 1

    assert link_authority.operations == [
        "source_identity_bindings",
        "link_types",
        "link_assertions",
    ]


def test_capability_declares_rest_sdk_and_mcp_agent_surface() -> None:
    spec = ENTITY_AUTHORITY_BATCH_INGEST
    surfaces = {binding.surface.value: binding.status.value for binding in spec.surfaces}

    assert spec.policy.allowed_roles == ("admin", "platform_operator")
    assert spec.execution.idempotency.value == "required"
    assert surfaces["api"] == "implemented"
    assert surfaces["sdk"] == "implemented"
    assert surfaces["agent"] == "implemented"
    assert spec.mcp is not None
    assert spec.mcp.tool_name == "ingest_entity_authority_batch"
    assert spec.mcp_projection()["annotations"] == {
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
    }
    assert "/api/platform/v1/entity-authority/batches" in spec.openapi_projection()[
        "paths"
    ]


def test_mcp_tool_enforces_context_and_executes_canonical_contract() -> None:
    item = _temporal_item(recorded_by="agent:mcp-operator")
    batch = _batch(item)
    result = EntityAuthorityBatchResponse(
        tenant_id=TENANT,
        batch_type=batch.batch_type,
        idempotency_key=batch.idempotency_key,
        request_sha256=batch.request_sha256,
        state_fingerprint="b" * 64,
        logical_operation_count=1,
        batch_count=1,
        entity_count=1,
        binding_count=0,
        link_type_count=0,
        link_assertion_count=0,
    )
    tenant_token = current_tenant_id.set(TENANT)
    user_token = current_user_id.set("mcp-operator")
    role_token = current_user_role.set("analyst")
    try:
        denied = json.loads(
            _mcp_ingest_entity_authority_batch(
                batch.batch_type,
                TENANT,
                batch.idempotency_key,
                [item.model_dump(mode="json")],
            )
        )
        assert denied["code"] == "platform_role_required"

        current_user_role.set("platform_operator")
        mismatch = json.loads(
            _mcp_ingest_entity_authority_batch(
                batch.batch_type,
                "tenant-b",
                batch.idempotency_key,
                [item.model_dump(mode="json")],
            )
        )
        assert mismatch["code"] == "tenant_mismatch"

        spoofed = item.model_copy(update={"recorded_by": "agent:spoofed"})
        actor_error = json.loads(
            _mcp_ingest_entity_authority_batch(
                batch.batch_type,
                TENANT,
                batch.idempotency_key,
                [spoofed.model_dump(mode="json")],
            )
        )
        assert actor_error["code"] == "actor_mismatch"

        with patch(
            "data_agent.entity_authority_batch.execute_entity_authority_batch",
            return_value=result,
        ) as execute:
            payload = json.loads(
                _mcp_ingest_entity_authority_batch(
                    batch.batch_type,
                    TENANT,
                    batch.idempotency_key,
                    [item.model_dump(mode="json")],
                )
            )
        assert payload["state_fingerprint"] == "b" * 64
        assert payload["technical_baseline_status"] == (
            "technical_baseline_unreviewed"
        )
        request = execute.call_args.args[0]
        assert request.tenant_id == TENANT
        assert request.items[0].recorded_by == "agent:mcp-operator"
    finally:
        current_user_role.reset(role_token)
        current_user_id.reset(user_token)
        current_tenant_id.reset(tenant_token)


@pytest.mark.parametrize(
    ("user", "expected_status", "expected_code"),
    (
        (None, 401, "unauthorized"),
        (_user(role="viewer"), 403, "platform_role_required"),
    ),
)
def test_route_requires_authentication_and_governance_role(
    user,
    expected_status: int,
    expected_code: str,
) -> None:
    request = _request(body=_batch().model_dump(mode="json"))
    with patch.object(routes, "_get_user_from_request", return_value=user):
        response = asyncio.run(routes.ingest_entity_authority_batch(request))

    assert response.status_code == expected_status
    assert json.loads(response.body)["error"]["code"] == expected_code


def test_route_rejects_contract_drift_tenant_and_actor_spoofing() -> None:
    drift = _request(
        body={},
        headers={"X-GDA-Capability-Fingerprint": "0" * 64},
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        drift_response = asyncio.run(routes.ingest_entity_authority_batch(drift))
    assert drift_response.status_code == 409
    assert json.loads(drift_response.body)["error"]["code"] == (
        "capability_contract_mismatch"
    )

    tenant_body = _batch(
        _temporal_item(tenant_id="tenant-b"),
        tenant_id="tenant-b",
    ).model_dump(mode="json")
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        tenant_response = asyncio.run(
            routes.ingest_entity_authority_batch(_request(body=tenant_body))
        )
    assert tenant_response.status_code == 403
    assert json.loads(tenant_response.body)["error"]["code"] == "tenant_mismatch"

    actor_body = _batch(
        _temporal_item(recorded_by="human:spoofed")
    ).model_dump(mode="json")
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        actor_response = asyncio.run(
            routes.ingest_entity_authority_batch(_request(body=actor_body))
        )
    assert actor_response.status_code == 403
    assert json.loads(actor_response.body)["error"]["code"] == "actor_mismatch"

    mismatch_request = _request(
        body=_batch().model_dump(mode="json"),
        headers={"idempotency-key": "different.request.key"},
    )
    with patch.object(routes, "_get_user_from_request", return_value=_user()):
        mismatch_response = asyncio.run(
            routes.ingest_entity_authority_batch(mismatch_request)
        )
    assert mismatch_response.status_code == 409
    assert json.loads(mismatch_response.body)["error"]["code"] == (
        "idempotency_key_mismatch"
    )


def test_route_returns_standard_envelope_and_maps_authority_conflicts() -> None:
    batch = _batch()
    result = EntityAuthorityBatchResponse(
        tenant_id=TENANT,
        batch_type=batch.batch_type,
        idempotency_key=batch.idempotency_key,
        request_sha256=batch.request_sha256,
        state_fingerprint="a" * 64,
        logical_operation_count=1,
        batch_count=1,
        entity_count=1,
        binding_count=0,
        link_type_count=0,
        link_assertion_count=0,
    )
    request = _request(
        body=batch.model_dump(mode="json"),
        headers={
            "x-request-id": "request-1",
            "X-GDA-Capability-Fingerprint": ENTITY_AUTHORITY_BATCH_INGEST.fingerprint,
            "idempotency-key": batch.idempotency_key,
        },
    )
    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(routes, "execute_entity_authority_batch", return_value=result),
    ):
        response = asyncio.run(routes.ingest_entity_authority_batch(request))

    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["request_id"] == "request-1"
    assert ENTITY_AUTHORITY_BATCH_INGEST.validate_output(payload["data"])[
        "state_fingerprint"
    ] == "a" * 64

    with (
        patch.object(routes, "_get_user_from_request", return_value=_user()),
        patch.object(
            routes,
            "execute_entity_authority_batch",
            side_effect=TemporalEntityConflictError("conflicting replay"),
        ),
    ):
        conflict = asyncio.run(
            routes.ingest_entity_authority_batch(
                _request(body=batch.model_dump(mode="json"))
            )
        )
    assert conflict.status_code == 409
    assert json.loads(conflict.body)["error"]["code"] == "temporal_entity_conflict"


def test_entity_authority_batch_route_is_registered() -> None:
    paths = {route.path for route in routes.get_platform_gateway_routes()}
    assert "/api/platform/v1/entity-authority/batches" in paths
